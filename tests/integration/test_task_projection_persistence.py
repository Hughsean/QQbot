from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.inbound.workers.task_projection import AgendaProjectionOutboxRelay
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.jobs import SqlJobQueue
from qq_time_agent.adapters.outbound.persistence.operations_tables import JobRow, OutboxEventRow
from qq_time_agent.adapters.outbound.persistence.outbox import SqlOutbox
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.agenda.application.service import AgendaService
from qq_time_agent.modules.agenda.contracts import AgendaDraft
from qq_time_agent.modules.agenda.infrastructure.repository import SqlAgendaRepository
from qq_time_agent.modules.agenda.infrastructure.tables import AgendaEntryRow
from qq_time_agent.modules.task_projection.domain.models import (
    TaskProjectionCursor,
    TaskProjectionMapping,
    TaskProjectionStatus,
    TaskProjectionTarget,
)
from qq_time_agent.modules.task_projection.infrastructure.repository import (
    SqlTaskProjectionCursorRepository,
    SqlTaskProjectionMappingRepository,
    SqlTaskProjectionTargetRepository,
)
from qq_time_agent.modules.task_projection.infrastructure.tables import (
    TaskProjectionCursorRow,
    TaskProjectionMappingRow,
    TaskProjectionTargetRow,
)

pytestmark = pytest.mark.integration


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


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


@pytest.mark.asyncio
async def test_mapping_is_agenda_unique_and_persists_projection_state(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlTaskProjectionMappingRepository(sessions)
    connection_id, entry_id = uuid4(), uuid4()
    mapping = TaskProjectionMapping.pending(
        "integration-owner", entry_id, 1, connection_id, "managed-list"
    )
    duplicate = TaskProjectionMapping.pending(
        "integration-owner", entry_id, 1, connection_id, "managed-list"
    )
    try:
        stored = await repository.add_or_get(mapping)
        repeated = await repository.add_or_get(duplicate)
        assert repeated.mapping_id == stored.mapping_id

        stored.activate(2, "task-one", "revision-one", datetime(2026, 9, 13, tzinfo=UTC))
        await repository.save(stored, stored.version - 1)
        loaded = await repository.get_for_agenda(connection_id, entry_id)
        assert loaded is not None
        assert loaded.status is TaskProjectionStatus.ACTIVE
        assert loaded.agenda_entry_version == 2
        assert loaded.provider_task_ref == "task-one"
        external = await repository.get_for_external_task(connection_id, "managed-list", "task-one")
        assert external is not None and external.mapping_id == stored.mapping_id
        external.observe(True, "revision-two", datetime(2026, 9, 13, 1, tzinfo=UTC))
        await repository.save(external, external.version - 1)
        observed = await repository.get_for_agenda(connection_id, entry_id)
        assert observed is not None and observed.last_observed_completion is True
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(TaskProjectionMappingRow).where(
                    TaskProjectionMappingRow.connection_id == connection_id
                )
            )


@pytest.mark.asyncio
async def test_delta_cursor_is_durable_versioned_and_resettable(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlTaskProjectionCursorRepository(sessions)
    connection_id = uuid4()
    now = datetime(2026, 9, 13, tzinfo=UTC)
    cursor = TaskProjectionCursor.create(connection_id, "managed-list", "cursor-one", now)
    try:
        await repository.save(cursor, None)
        loaded = await repository.get(connection_id, "managed-list")
        assert loaded is not None and loaded.opaque_cursor == "cursor-one"
        loaded.advance("cursor-two", now + timedelta(minutes=1))
        await repository.save(loaded, loaded.version - 1)
        advanced = await repository.get(connection_id, "managed-list")
        assert advanced is not None and advanced.opaque_cursor == "cursor-two"
        await repository.delete(connection_id, "managed-list")
        assert await repository.get(connection_id, "managed-list") is None
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(TaskProjectionCursorRow).where(
                    TaskProjectionCursorRow.connection_id == connection_id
                )
            )


@pytest.mark.asyncio
async def test_agenda_outbox_relays_once_to_durable_projection_job(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 9, 13, 8, tzinfo=UTC)
    proposal_id = uuid4()
    agenda = AgendaService(SqlAgendaRepository(sessions, Clock(now)))
    entry = await agenda.create_entry(
        uuid4(),
        AgendaDraft(
            "TASK_BLOCK",
            "Task projection relay integration",
            now,
            now + timedelta(hours=1),
            "Asia/Shanghai",
            ("integration:task-projection",),
            proposal_id,
        ),
        f"task-projection-relay:{proposal_id}",
    )
    relay = AgendaProjectionOutboxRelay(SqlOutbox(sessions), SqlJobQueue(sessions), Clock(now))
    try:
        assert await relay.enqueue_due() >= 1
        async with sessions() as session:
            event = await session.scalar(
                select(OutboxEventRow).where(
                    OutboxEventRow.aggregate_ref == f"agenda:{entry.agenda_entry_id}"
                )
            )
            assert event is not None
            job = await session.scalar(
                select(JobRow).where(
                    JobRow.idempotency_key == f"task-projection-event:{event.event_id}"
                )
            )
            assert event.published_at == now
            assert job is not None and job.kind == "task-projection-upsert"
        assert await relay.enqueue_due() == 0
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(JobRow).where(
                    JobRow.payload["agenda_entry_id"].as_string() == str(entry.agenda_entry_id)
                )
            )
            await session.execute(
                delete(OutboxEventRow).where(
                    OutboxEventRow.aggregate_ref == f"agenda:{entry.agenda_entry_id}"
                )
            )
            await session.execute(
                delete(AgendaEntryRow).where(
                    AgendaEntryRow.agenda_entry_id == entry.agenda_entry_id
                )
            )
