"""PostgreSQL idempotent Normalization repository."""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.normalization.contracts import NormalizedContentView
from qq_time_agent.modules.normalization.infrastructure.tables import NormalizedContentRow


class SqlNormalizedContentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def upsert(
        self,
        inbox_item_id: UUID,
        subject: str,
        body: str,
        source_hash: str,
        normalizer_version: str,
        source_ref: str | None,
    ) -> NormalizedContentView:
        values = {
            "inbox_item_id": inbox_item_id,
            "subject": subject,
            "body": body,
            "source_hash": source_hash,
            "normalizer_version": normalizer_version,
            "source_ref": source_ref,
        }
        async with self._sessions.begin() as session:
            await session.execute(
                insert(NormalizedContentRow)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[NormalizedContentRow.inbox_item_id], set_=values
                )
            )
        return NormalizedContentView(
            inbox_item_id, subject, body, source_hash, normalizer_version, source_ref
        )

    async def get(self, inbox_item_id: UUID) -> NormalizedContentView | None:
        async with self._sessions() as session:
            row = await session.get(NormalizedContentRow, inbox_item_id)
            if row is None:
                return None
            return NormalizedContentView(
                row.inbox_item_id,
                row.subject,
                row.body,
                row.source_hash,
                row.normalizer_version,
                row.source_ref,
            )
