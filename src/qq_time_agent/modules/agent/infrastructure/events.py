"""Persist AgentRun execution timeline events."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agent.contracts import (
    AgentRunEvent,
    AgentRunEventType,
    AgentRunEventView,
)
from qq_time_agent.modules.agent.infrastructure.tables import AgentRunEventRow, AgentRunRow


class SqlAgentRunEventRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(self, event: AgentRunEvent) -> AgentRunEventView:
        async with self._sessions.begin() as session:
            run = await session.get(AgentRunRow, event.run_id, with_for_update=True)
            if run is None:
                raise LookupError("AgentRun does not exist")
            existing = await session.scalar(
                select(AgentRunEventRow).where(
                    AgentRunEventRow.run_id == event.run_id,
                    AgentRunEventRow.idempotency_key == event.idempotency_key,
                )
            )
            if existing is not None:
                return _view(existing)
            last = await session.scalar(
                select(func.max(AgentRunEventRow.sequence)).where(
                    AgentRunEventRow.run_id == event.run_id
                )
            )
            row = AgentRunEventRow(
                event_id=event.event_id,
                run_id=event.run_id,
                sequence=(last or 0) + 1,
                event_type=event.event_type.value,
                step=event.step,
                occurred_at=event.occurred_at,
                status=event.status,
                duration_ms=event.duration_ms,
                error_class=event.error_class,
                tool_name=event.tool_name,
                call_id=event.call_id,
                invocation_id=event.invocation_id,
                idempotency_key=event.idempotency_key,
                metadata_json=dict(event.metadata),
            )
            session.add(row)
            await session.flush()
            return _view(row)

    async def list_for_run(self, run_id: UUID, limit: int = 500) -> tuple[AgentRunEventView, ...]:
        if limit < 1 or limit > 5000:
            raise ValueError("AgentRun event limit must be between 1 and 5000")
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AgentRunEventRow)
                .where(AgentRunEventRow.run_id == run_id)
                .order_by(AgentRunEventRow.sequence)
                .limit(limit)
            )
            return tuple(_view(row) for row in rows)

    async def list_for_scope(
        self, scope_id: UUID, scope_type: str, limit: int = 500
    ) -> tuple[AgentRunEventView, ...]:
        if limit < 1 or limit > 5000:
            raise ValueError("AgentRun event limit must be between 1 and 5000")
        column = {
            "conversation": AgentRunRow.conversation_id,
            "event": AgentRunRow.event_case_id,
        }.get(scope_type)
        if column is None:
            raise ValueError("Agent context scope type is invalid")
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AgentRunEventRow)
                .join(AgentRunRow, AgentRunRow.run_id == AgentRunEventRow.run_id)
                .where(column == scope_id)
                .order_by(
                    AgentRunEventRow.occurred_at,
                    AgentRunEventRow.run_id,
                    AgentRunEventRow.sequence,
                )
                .limit(limit)
            )
            return tuple(_view(row) for row in rows)


def _view(row: AgentRunEventRow) -> AgentRunEventView:
    return AgentRunEventView(
        row.event_id,
        row.run_id,
        AgentRunEventType(row.event_type),
        row.occurred_at,
        row.step,
        row.status,
        row.duration_ms,
        row.error_class,
        row.tool_name,
        row.call_id,
        row.invocation_id,
        dict(row.metadata_json),
    )
