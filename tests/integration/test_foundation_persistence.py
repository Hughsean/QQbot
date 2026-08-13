from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.health import DatabaseReadinessProbe
from qq_time_agent.adapters.outbound.persistence.jobs import SqlJobQueue
from qq_time_agent.adapters.outbound.persistence.operations_tables import JobRow, OutboxEventRow
from qq_time_agent.adapters.outbound.persistence.outbox import SqlOutbox
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.events import EventEnvelope
from qq_time_agent.contracts.jobs import JobRequest
from qq_time_agent.modules.data_lifecycle.domain.models import Tombstone, TombstoneStatus
from qq_time_agent.modules.data_lifecycle.infrastructure.repository import SqlTombstoneRepository
from qq_time_agent.modules.data_lifecycle.infrastructure.tables import PurgeResultRow, TombstoneRow

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


@pytest.mark.asyncio
async def test_pgvector_extension_and_migration_are_active(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        extension = await connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        revision = await connection.scalar(
            select(text("version_num")).select_from(text("alembic_version"))
        )
        job_constraint = await connection.scalar(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'platform_jobs'::regclass "
                "AND contype = 'u' AND conname = 'uq_platform_jobs_idempotency'"
            )
        )
    assert extension is not None
    assert revision == "0013_schema_alignment"
    assert job_constraint == "uq_platform_jobs_idempotency"

    health = await DatabaseReadinessProbe(engine).check()
    assert health.available and health.vector_enabled


@pytest.mark.asyncio
async def test_job_enqueue_and_concurrent_lease_are_idempotent(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    queue = SqlJobQueue(sessions)
    now = datetime(2026, 8, 13, tzinfo=UTC)
    key = f"integration:{uuid4()}"
    request = JobRequest("integration", {"value": "synthetic"}, key, now)
    first = await queue.enqueue(request)
    second = await queue.enqueue(request)

    lease = await queue.lease_due(now, "worker-a", 1, timedelta(minutes=1))
    competing = await queue.lease_due(now, "worker-b", 1, timedelta(minutes=1))
    assert first == second
    assert [item.job_id for item in lease] == [first]
    assert competing == []

    await queue.complete(lease[0], now)
    async with sessions.begin() as session:
        await session.execute(delete(JobRow).where(JobRow.job_id == first))


@pytest.mark.asyncio
async def test_qq_mail_jobs_retry_and_disconnect_cancellation(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    queue = SqlJobQueue(sessions)
    now = datetime(2026, 8, 13, tzinfo=UTC)
    connection_id = uuid4()
    request = JobRequest(
        "qq-mail-sync",
        {"connection_id": str(connection_id)},
        f"qq-mail-sync:{connection_id}:integration",
        now,
    )
    job_id = await queue.enqueue(request)
    lease = (await queue.lease_due(now, "worker-qq", 1, timedelta(minutes=1)))[0]
    await queue.fail(lease, now, "TransientProvider", now + timedelta(seconds=30))
    retry = await queue.status(job_id)
    assert retry is not None and retry.status == "RETRY_WAIT"
    assert await queue.cancel_pending_for_connection(connection_id, now) == 1
    cancelled = await queue.status(job_id)
    assert cancelled is not None and cancelled.status == "CANCELLED"
    async with sessions.begin() as session:
        await session.execute(delete(JobRow).where(JobRow.job_id == job_id))


@pytest.mark.asyncio
async def test_outbox_append_is_transactional_and_publish_is_idempotent(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    outbox = SqlOutbox(sessions)
    event_id = uuid4()
    occurred_at = datetime(2026, 8, 13, tzinfo=UTC)
    event = EventEnvelope(event_id, "SyntheticEvent", 1, "test:1", {}, occurred_at)

    async with sessions.begin() as session:
        outbox.append(session, event)
    pending = await outbox.unpublished()
    assert event_id in {item.event_id for item in pending}
    await outbox.mark_published(event_id, occurred_at)
    await outbox.mark_published(event_id, occurred_at)

    async with sessions.begin() as session:
        row = await session.get(OutboxEventRow, event_id)
        assert row is not None and row.published_at == occurred_at
        await session.execute(delete(OutboxEventRow).where(OutboxEventRow.event_id == event_id))


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


@pytest.mark.asyncio
async def test_tombstone_repository_round_trip_and_idempotent_module_result(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 13, tzinfo=UTC)
    repository = SqlTombstoneRepository(sessions, FixedClock(now))
    tombstone = Tombstone.request("synthetic:source", now - timedelta(hours=25), now)
    stored = await repository.add(tombstone)
    assert stored.tombstone_id == tombstone.tombstone_id
    duplicate = await repository.add(Tombstone.request("synthetic:source", now, now))
    assert duplicate.tombstone_id == tombstone.tombstone_id
    await repository.record_module_purge(tombstone.tombstone_id, "knowledge", 2)
    await repository.record_module_purge(tombstone.tombstone_id, "knowledge", 0)

    due = await repository.find_due(now, 10)
    loaded = next(item for item in due if item.tombstone_id == tombstone.tombstone_id)
    assert loaded.completed_modules == {"knowledge"}
    await repository.mark_complete(tombstone.tombstone_id)

    async with sessions.begin() as session:
        row = await session.get(TombstoneRow, tombstone.tombstone_id)
        assert row is not None and row.status == TombstoneStatus.COMPLETE.value
        await session.execute(
            delete(PurgeResultRow).where(PurgeResultRow.tombstone_id == tombstone.tombstone_id)
        )
        await session.execute(
            delete(TombstoneRow).where(TombstoneRow.tombstone_id == tombstone.tombstone_id)
        )
