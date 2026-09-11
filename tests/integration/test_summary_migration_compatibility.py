import os
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
ROOT = Path(__file__).resolve().parents[2]


async def test_0028_backfills_existing_0027_summaries() -> None:
    config = load_runtime_config().database
    database_name = f"qq_time_agent_test_summary_{uuid4().hex}"
    admin = create_database_engine(replace(config, name="postgres"))
    target = create_database_engine(replace(config, name=database_name))
    try:
        await _database_command(admin, f'CREATE DATABASE "{database_name}"')
        _alembic(database_name, "upgrade", "0027_conversation_events")
        expected = await _insert_legacy_summaries(target)

        _alembic(database_name, "upgrade", "0028_summary_contract")

        async with target.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        text(
                            "SELECT summary_id, source_hash, idempotency_key, structured_json "
                            "FROM agent_conversation_summaries ORDER BY from_sequence"
                        )
                    )
                )
                .mappings()
                .all()
            )
        assert [row["source_hash"] for row in rows] == expected
        assert len({row["idempotency_key"] for row in rows}) == 2
        assert all(row["idempotency_key"].startswith("legacy-summary:") for row in rows)
        assert all(row["structured_json"] == {} for row in rows)

        _alembic(database_name, "downgrade", "0027_conversation_events")
        async with target.connect() as connection:
            count = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'agent_conversation_summaries' "
                    "AND column_name IN ('source_hash','structured_json','idempotency_key')"
                )
            )
        assert count == 0
    finally:
        await target.dispose()
        await _database_command(admin, f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.dispose()


async def _insert_legacy_summaries(engine) -> list[str]:
    user_id = "test-migration-owner"
    scope_id = uuid4()
    event_ids = [uuid4() for _ in range(4)]
    hashes = [sha256(f"event-{index}".encode()).hexdigest() for index in range(4)]
    async with engine.begin() as connection:
        for index in range(4):
            await connection.execute(
                text(
                    "INSERT INTO agent_conversation_events "
                    "(event_id,scope_type,scope_id,user_id,sequence,event_type,role,"
                    "occurred_at,created_at,content,content_hash,idempotency_key,metadata) "
                    "VALUES (:event_id,'conversation',:scope_id,:user_id,:sequence,:event_type,"
                    ":role,now(),now(),:content,:content_hash,:key,'{}'::jsonb)"
                ),
                {
                    "event_id": event_ids[index],
                    "scope_id": scope_id,
                    "user_id": user_id,
                    "sequence": index + 1,
                    "event_type": "USER_MESSAGE" if index % 2 == 0 else "AGENT_REPLY",
                    "role": "user" if index % 2 == 0 else "agent",
                    "content": f"synthetic-{index}",
                    "content_hash": hashes[index],
                    "key": f"migration-event:{event_ids[index]}",
                },
            )
        for start in (1, 3):
            await connection.execute(
                text(
                    "INSERT INTO agent_conversation_summaries "
                    "(summary_id,scope_type,scope_id,user_id,summary_kind,from_sequence,"
                    "to_sequence,content,content_hash,created_at) VALUES "
                    "(:summary_id,'conversation',:scope_id,:user_id,'timeline',:start,"
                    ":finish,:content,:content_hash,now())"
                ),
                {
                    "summary_id": uuid4(),
                    "scope_id": scope_id,
                    "user_id": user_id,
                    "start": start,
                    "finish": start + 1,
                    "content": f"legacy-summary-{start}",
                    "content_hash": sha256(f"summary-{start}".encode()).hexdigest(),
                },
            )
    return [_source_hash(user_id, scope_id, start, event_ids, hashes) for start in (1, 3)]


def _source_hash(user_id, scope_id, start: int, event_ids, hashes) -> str:
    parts = [
        f"{user_id}:conversation:{scope_id}:{index + 1}:{event_ids[index]}:{hashes[index]}"
        for index in range(start - 1, start + 1)
    ]
    return sha256("|".join(parts).encode()).hexdigest()


def _alembic(database_name: str, action: str, revision: str) -> None:
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "DATABASE_NAME": database_name})
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", action, revision],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
        text=True,
    )


async def _database_command(engine, statement: str) -> None:
    async with engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(statement))
