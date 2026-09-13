from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.task_projection.domain.models import TaskProjectionTarget
from qq_time_agent.modules.task_projection.infrastructure.repository import (
    SqlTaskProjectionTargetRepository,
)
from qq_time_agent.modules.task_projection.infrastructure.tables import TaskProjectionTargetRow

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


@pytest.mark.asyncio
async def test_target_is_connection_unique_idempotent_and_versioned(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlTaskProjectionTargetRepository(sessions)
    connection_id = uuid4()
    now = datetime(2026, 9, 13, tzinfo=UTC)
    first = TaskProjectionTarget.resolve(
        "integration-owner", connection_id, "managed-list", "小智建议", now
    )
    duplicate = TaskProjectionTarget.resolve(
        "integration-owner", connection_id, "other-list", "小智建议", now
    )
    try:
        stored = await repository.add_or_get(first)
        repeated = await repository.add_or_get(duplicate)
        assert repeated.target_id == stored.target_id
        assert repeated.provider_list_ref == "managed-list"

        changed_at = now + timedelta(minutes=1)
        assert stored.rebind("replacement-list", "小智建议", changed_at)
        await repository.save(stored, stored.version - 1)
        loaded = await repository.get_for_connection(connection_id)
        assert loaded is not None
        assert loaded.provider_list_ref == "replacement-list"
        assert loaded.version == 2
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(TaskProjectionTargetRow).where(
                    TaskProjectionTargetRow.connection_id == connection_id
                )
            )
