"""Normalization-owned idempotent deletion adapter."""

from typing import cast
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.data_lifecycle.contracts import PurgeResult
from qq_time_agent.modules.normalization.infrastructure.tables import (
    NormalizedAssetRow,
    NormalizedContentRow,
)


class NormalizationPurgeAdapter:
    module_name = "normalization"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def purge_subject(self, subject_ref: str, tombstone_id: UUID) -> PurgeResult:
        del tombstone_id
        async with self._sessions.begin() as session:
            content_result = await session.execute(
                delete(NormalizedContentRow).where(NormalizedContentRow.source_ref == subject_ref)
            )
            asset_result = await session.execute(
                delete(NormalizedAssetRow).where(NormalizedAssetRow.source_ref == subject_ref)
            )
            count = int(cast("CursorResult[tuple[()]]", content_result).rowcount or 0)
            count += int(cast("CursorResult[tuple[()]]", asset_result).rowcount or 0)
        return PurgeResult(self.module_name, count, count == 0)
