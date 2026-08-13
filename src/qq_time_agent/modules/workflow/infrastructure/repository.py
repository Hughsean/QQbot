"""PostgreSQL workflow checkpoint repository with optimistic versioning."""

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.workflow.application.ports import WorkflowCheckpoint
from qq_time_agent.modules.workflow.infrastructure.tables import UnderstandingCheckpointRow


class SqlWorkflowCheckpointRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, inbox_item_id: UUID) -> WorkflowCheckpoint | None:
        async with self._sessions() as session:
            row = await session.get(UnderstandingCheckpointRow, inbox_item_id)
            if row is None:
                return None
            return WorkflowCheckpoint(
                row.inbox_item_id,
                row.phase,
                row.result_kind,
                row.candidate_id,
                row.confidence,
                row.review_reason,
                row.model_calls,
                row.version,
                row.source_ref,
            )

    async def save(self, value: WorkflowCheckpoint) -> None:
        values = {
            "inbox_item_id": value.inbox_item_id,
            "phase": value.phase,
            "result_kind": value.result_kind,
            "candidate_id": value.candidate_id,
            "confidence": value.confidence,
            "review_reason": value.review_reason,
            "model_calls": value.model_calls,
            "version": value.version,
            "source_ref": value.source_ref,
        }
        async with self._sessions.begin() as session:
            statement = insert(UnderstandingCheckpointRow).values(**values)
            if value.version == 1:
                statement = statement.on_conflict_do_nothing(
                    index_elements=[UnderstandingCheckpointRow.inbox_item_id]
                )
            else:
                statement = statement.on_conflict_do_update(
                    index_elements=[UnderstandingCheckpointRow.inbox_item_id],
                    set_=values,
                    where=(UnderstandingCheckpointRow.version == value.version - 1),
                )
            result = await session.execute(statement.returning(UnderstandingCheckpointRow.version))
            saved = result.scalar_one_or_none()
            if saved != value.version:
                existing = await session.get(UnderstandingCheckpointRow, value.inbox_item_id)
                if existing is None or existing.version < value.version:
                    raise RuntimeError("workflow checkpoint version conflict")
