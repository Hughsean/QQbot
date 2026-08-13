"""Inbox-owned idempotent source envelope and raw-content deletion."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.data_lifecycle.contracts import PurgeResult
from qq_time_agent.modules.inbox.infrastructure.repository import _lock_connection
from qq_time_agent.modules.inbox.infrastructure.tables import (
    InboxItemRow,
    InboxRawContentRow,
    InboxSourceDeletionRow,
)


class InboxPurgeAdapter:
    module_name = "inbox"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def purge_subject(self, subject_ref: str, tombstone_id: UUID) -> PurgeResult:
        del tombstone_id
        parsed = _parse_source_ref(subject_ref)
        if parsed is None:
            return PurgeResult(self.module_name, 0, True)
        connection_id, external_id = parsed
        async with self._sessions.begin() as session:
            await _lock_connection(session, connection_id)
            matching = tuple(
                await session.scalars(
                    select(InboxItemRow)
                    .where(
                        InboxItemRow.connection_id == connection_id,
                        InboxItemRow.external_id == external_id,
                    )
                    .with_for_update()
                )
            )
            if not matching:
                await session.execute(
                    insert(InboxSourceDeletionRow)
                    .values(connection_id=connection_id, external_id=external_id)
                    .on_conflict_do_nothing()
                )
                return PurgeResult(self.module_name, 0, True)
            await session.execute(
                insert(InboxSourceDeletionRow)
                .values(
                    [
                        {
                            "connection_id": connection_id,
                            "external_id": row.external_id,
                            "dedupe_key": row.dedupe_key,
                        }
                        for row in matching
                    ]
                )
                .on_conflict_do_nothing()
            )
            item_ids = tuple(row.inbox_item_id for row in matching)
            raw_ids = tuple(row.raw_content_ref for row in matching)
            await session.execute(
                delete(InboxItemRow).where(InboxItemRow.inbox_item_id.in_(item_ids))
            )
            await session.execute(
                delete(InboxRawContentRow).where(InboxRawContentRow.raw_content_id.in_(raw_ids))
            )
            return PurgeResult(self.module_name, len(matching))


def _parse_source_ref(subject_ref: str) -> tuple[UUID, str] | None:
    parts = subject_ref.split(":", 2)
    if len(parts) != 3 or parts[0] not in {
        "mail",
        "qq-mail",
        "qq",
        "qq-forward",
        "owner-note",
    }:
        return None
    try:
        connection_id = UUID(parts[1])
    except ValueError:
        return None
    return connection_id, parts[2]
