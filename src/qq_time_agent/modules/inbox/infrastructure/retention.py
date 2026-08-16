"""Inbox-owned source retention discovery."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.inbox.application.source_refs import build_source_ref
from qq_time_agent.modules.inbox.infrastructure.tables import InboxItemRow


class InboxExpiredSourceAdapter:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def find_expired(self, cutoff: datetime, limit: int) -> tuple[str, ...]:
        async with self._sessions() as session:
            rows = tuple(
                await session.scalars(
                    select(InboxItemRow)
                    .where(
                        InboxItemRow.source_type.in_(
                            (
                                SourceType.MICROSOFT_MAIL.value,
                                SourceType.QQ_MAIL.value,
                                SourceType.QQ_FORWARD.value,
                            )
                        ),
                        InboxItemRow.occurred_at <= cutoff,
                    )
                    .order_by(InboxItemRow.occurred_at, InboxItemRow.inbox_item_id)
                    .limit(limit)
                )
            )
        return tuple(
            build_source_ref(SourceType(row.source_type), row.connection_id, row.external_id)
            for row in rows
        )
