"""Append-only PostgreSQL Audit repository."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.audit.contracts import AuditEvent
from qq_time_agent.modules.audit.infrastructure.tables import AuditEventRow


class SqlAuditRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, event: AuditEvent) -> None:
        async with self._sessions.begin() as session:
            session.add(
                AuditEventRow(
                    audit_id=uuid4(),
                    event_type=event.event_type,
                    actor_ref=event.actor_ref,
                    subject_ref=event.subject_ref,
                    outcome=event.outcome,
                    occurred_at=event.occurred_at,
                    event_metadata=event.metadata,
                )
            )

    async def update(self, audit_id: object, values: object) -> None:
        del audit_id, values
        raise PermissionError("Audit records are append-only")

    async def delete(self, audit_id: object) -> None:
        del audit_id
        raise PermissionError("Audit records are removed only by configured retention")
