from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.operations_tables import JobRow
from qq_time_agent.adapters.outbound.persistence.retention import OperationalExpiryAdapter
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.ai_gateway.application.ports import InvocationMetadata
from qq_time_agent.modules.ai_gateway.infrastructure.repository import SqlInvocationRepository
from qq_time_agent.modules.ai_gateway.infrastructure.retention import AIGatewayExpiryAdapter
from qq_time_agent.modules.ai_gateway.infrastructure.tables import ModelInvocationRow
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.contracts import AuditEvent
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.audit.infrastructure.retention import AuditExpiryAdapter
from qq_time_agent.modules.audit.infrastructure.tables import AuditEventRow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


async def test_configured_expiry_adapters_delete_only_old_owned_rows(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    old_id, new_id = uuid4(), uuid4()
    audit_old, audit_new = "retention-old", "retention-new"
    await SqlInvocationRepository(sessions).add(_invocation(old_id, now - timedelta(days=181)))
    await SqlInvocationRepository(sessions).add(_invocation(new_id, now - timedelta(days=179)))
    audit = AuditService(SqlAuditRepository(sessions))
    await audit.append(_audit(audit_old, now - timedelta(days=366)))
    await audit.append(_audit(audit_new, now - timedelta(days=364)))
    job_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            JobRow(
                job_id=job_id,
                kind="synthetic-retention",
                payload={},
                status="COMPLETE",
                idempotency_key=f"retention:{job_id}",
                available_at=now - timedelta(days=31),
                lease_owner=None,
                lease_until=None,
                attempt_count=1,
                max_attempts=1,
                last_error_class=None,
                last_error_detail=None,
                created_at=now - timedelta(days=31),
                updated_at=now - timedelta(days=31),
            )
        )
    try:
        assert (
            await AIGatewayExpiryAdapter(sessions).purge_expired(now - timedelta(days=180), 10)
        ).deleted_count == 1
        assert (
            await AuditExpiryAdapter(sessions).purge_expired(now - timedelta(days=365), 10)
        ).deleted_count == 1
        assert (
            await OperationalExpiryAdapter(sessions).purge_expired(now - timedelta(days=30), 10)
        ).deleted_count >= 1
        async with sessions() as session:
            assert await session.get(ModelInvocationRow, old_id) is None
            assert await session.get(ModelInvocationRow, new_id) is not None
            refs = set(
                await session.scalars(
                    select(AuditEventRow.subject_ref).where(
                        AuditEventRow.subject_ref.in_((audit_old, audit_new))
                    )
                )
            )
            assert refs == {audit_new}
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ModelInvocationRow).where(
                    ModelInvocationRow.invocation_id.in_((old_id, new_id))
                )
            )
            await session.execute(
                delete(AuditEventRow).where(AuditEventRow.subject_ref.in_((audit_old, audit_new)))
            )
            await session.execute(delete(JobRow).where(JobRow.job_id == job_id))


def _invocation(invocation_id: UUID, completed: datetime) -> InvocationMetadata:
    return InvocationMetadata(
        invocation_id,
        "synthetic",
        "v1",
        "FAST",
        "model",
        "SUCCEEDED",
        None,
        1,
        1,
        completed - timedelta(seconds=1),
        completed,
        1000,
    )


def _audit(subject_ref: str, occurred_at: datetime) -> AuditEvent:
    return AuditEvent("synthetic-retention", "test", subject_ref, "OK", occurred_at, {})
