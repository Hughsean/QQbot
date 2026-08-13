"""Connection-wide Inbox deletion queries isolated from normal ingestion."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.inbox.infrastructure.repository import _lock_connection, _source_ref
from qq_time_agent.modules.inbox.infrastructure.tables import (
    InboxConnectionStateRow,
    InboxItemRow,
    InboxSourceDeletionRow,
    InboxSyncCursorRow,
)


class SqlConnectionInboxDeletionRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def allow_connection(self, connection_id: UUID, now: datetime) -> None:
        async with self._sessions.begin() as session:
            await _lock_connection(session, connection_id)
            await session.execute(
                insert(InboxConnectionStateRow)
                .values(connection_id=connection_id, blocked=False, updated_at=now)
                .on_conflict_do_update(
                    index_elements=[InboxConnectionStateRow.connection_id],
                    set_={"blocked": False, "updated_at": now},
                )
            )

    async def block_connection(self, connection_id: UUID, now: datetime) -> None:
        async with self._sessions.begin() as session:
            await _lock_connection(session, connection_id)
            await self._set_connection_state(session, connection_id, True, now)

    async def mark_connection_deleted(self, connection_id: UUID, now: datetime) -> int:
        async with self._sessions.begin() as session:
            await _lock_connection(session, connection_id)
            await self._set_connection_state(session, connection_id, True, now)
            rows = tuple(
                await session.scalars(
                    select(InboxItemRow).where(InboxItemRow.connection_id == connection_id)
                )
            )
            if rows:
                await session.execute(
                    insert(InboxSourceDeletionRow)
                    .values(
                        [
                            {
                                "connection_id": connection_id,
                                "external_id": row.external_id,
                                "dedupe_key": row.dedupe_key,
                                "deleted_at": now,
                            }
                            for row in rows
                        ]
                    )
                    .on_conflict_do_nothing()
                )
            result = await session.execute(
                update(InboxItemRow)
                .where(
                    InboxItemRow.connection_id == connection_id,
                    InboxItemRow.deleted_at.is_(None),
                )
                .values(deleted_at=now)
            )
            return int(cast("CursorResult[tuple[()]]", result).rowcount or 0)

    async def list_source_refs_for_connection(
        self, connection_id: UUID, after_id: UUID | None, limit: int
    ) -> tuple[tuple[UUID, str], ...]:
        if limit < 1 or limit > 100:
            raise ValueError("connection source limit must be between 1 and 100")
        async with self._sessions() as session:
            statement = select(InboxItemRow).where(InboxItemRow.connection_id == connection_id)
            if after_id is not None:
                statement = statement.where(InboxItemRow.inbox_item_id > after_id)
            rows = tuple(
                await session.scalars(statement.order_by(InboxItemRow.inbox_item_id).limit(limit))
            )
        return tuple(
            (
                row.inbox_item_id,
                _source_ref(SourceType(row.source_type), row.connection_id, row.external_id),
            )
            for row in rows
        )

    async def delete_cursor(self, connection_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                delete(InboxSyncCursorRow).where(InboxSyncCursorRow.connection_id == connection_id)
            )

    @staticmethod
    async def _set_connection_state(
        session: AsyncSession, connection_id: UUID, blocked: bool, now: datetime
    ) -> None:
        await session.execute(
            insert(InboxConnectionStateRow)
            .values(connection_id=connection_id, blocked=blocked, updated_at=now)
            .on_conflict_do_update(
                index_elements=[InboxConnectionStateRow.connection_id],
                set_={"blocked": blocked, "updated_at": now},
            )
        )
