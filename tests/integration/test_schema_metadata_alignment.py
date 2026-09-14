import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
ROOT = Path(__file__).resolve().parents[2]


async def test_migrations_reproduce_model_metadata_exactly() -> None:
    """临时库从零升级到 head 后, ORM 元数据必须与迁移产物完全一致."""
    config = load_runtime_config().database
    database_name = f"qq_time_agent_test_meta_{uuid4().hex}"
    admin = create_database_engine(replace(config, name="postgres"))
    target = create_database_engine(replace(config, name=database_name))
    try:
        await _database_command(admin, f'CREATE DATABASE "{database_name}"')
        _run_alembic(database_name, "upgrade", "head")
        _run_alembic(database_name, "check")
        async with target.connect() as connection:
            heads = await connection.scalars(text("SELECT version_num FROM alembic_version"))
        assert len(heads.all()) == 1
    finally:
        await target.dispose()
        await _database_command(admin, f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.dispose()


def _run_alembic(database_name: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment.update({"APP_ENV": "test", "DATABASE_NAME": database_name})
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(arguments)} failed on {database_name}: "
            f"{completed.stdout}\n{completed.stderr}"
        )


async def _database_command(engine, statement: str) -> None:
    async with engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(statement))
