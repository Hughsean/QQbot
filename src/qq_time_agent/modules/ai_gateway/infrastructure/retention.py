"""AI Gateway-owned metadata retention adapter."""

from datetime import datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.ai_gateway.infrastructure.tables import ModelInvocationRow
from qq_time_agent.modules.data_lifecycle.contracts import PurgeResult


class AIGatewayExpiryAdapter:
    module_name = "ai_gateway"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def purge_expired(self, cutoff: datetime, limit: int) -> PurgeResult:
        async with self._sessions.begin() as session:
            ids = tuple(
                await session.scalars(
                    select(ModelInvocationRow.invocation_id)
                    .where(ModelInvocationRow.completed_at <= cutoff)
                    .order_by(ModelInvocationRow.completed_at)
                    .limit(limit)
                )
            )
            if not ids:
                return PurgeResult(self.module_name, 0, True)
            result = await session.execute(
                delete(ModelInvocationRow).where(ModelInvocationRow.invocation_id.in_(ids))
            )
            count = int(cast("CursorResult[tuple[()]]", result).rowcount or 0)
            return PurgeResult(self.module_name, count)
