"""Workflow-owned checkpoint purge adapter."""

from typing import cast
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.data_lifecycle.contracts import PurgeResult
from qq_time_agent.modules.workflow.infrastructure.tables import UnderstandingCheckpointRow


class WorkflowPurgeAdapter:
    module_name = "workflow"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def purge_subject(self, subject_ref: str, tombstone_id: UUID) -> PurgeResult:
        del tombstone_id
        async with self._sessions.begin() as session:
            result = await session.execute(
                delete(UnderstandingCheckpointRow).where(
                    UnderstandingCheckpointRow.source_ref == subject_ref
                )
            )
            count = int(cast("CursorResult[tuple[()]]", result).rowcount or 0)
        return PurgeResult(self.module_name, count, count == 0)
