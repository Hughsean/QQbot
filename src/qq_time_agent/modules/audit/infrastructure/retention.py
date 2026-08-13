"""Audit-owned configured retention adapter."""

from datetime import datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.audit.infrastructure.tables import AuditEventRow
from qq_time_agent.modules.data_lifecycle.contracts import PurgeResult


class AuditExpiryAdapter:
    module_name = "audit"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def purge_expired(self, cutoff: datetime, limit: int) -> PurgeResult:
        async with self._sessions.begin() as session:
            ids = tuple(
                await session.scalars(
                    select(AuditEventRow.audit_id)
                    .where(AuditEventRow.occurred_at <= cutoff)
                    .order_by(AuditEventRow.occurred_at)
                    .limit(limit)
                )
            )
            if not ids:
                return PurgeResult(self.module_name, 0, True)
            result = await session.execute(
                delete(AuditEventRow).where(AuditEventRow.audit_id.in_(ids))
            )
            count = int(cast("CursorResult[tuple[()]]", result).rowcount or 0)
            return PurgeResult(self.module_name, count)
