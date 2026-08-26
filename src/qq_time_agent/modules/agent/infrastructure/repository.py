"""PostgreSQL AgentRun repository with Inbox-level idempotency."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agent.contracts import AgentRun, AgentRunStatus
from qq_time_agent.modules.agent.infrastructure.tables import AgentRunRow, AgentToolCallRow


class SqlAgentRunRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_or_create(
        self, inbox_item_id: UUID, user_id: str, source_type: str, now: datetime
    ) -> AgentRun:
        run_id = uuid4()
        values = {
            "run_id": run_id,
            "inbox_item_id": inbox_item_id,
            "user_id": user_id,
            "source_type": source_type,
            "status": AgentRunStatus.PENDING.value,
            "step": 0,
            "observations": [],
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        async with self._sessions.begin() as session:
            await session.execute(
                insert(AgentRunRow)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_agent_runs_inbox_item")
            )
            row = await session.scalar(
                select(AgentRunRow).where(AgentRunRow.inbox_item_id == inbox_item_id)
            )
            if row is None:
                raise RuntimeError("AgentRun idempotent insert lost stored row")
            return _to_run(row)

    async def get(self, run_id: UUID) -> AgentRun | None:
        async with self._sessions() as session:
            row = await session.get(AgentRunRow, run_id)
            return None if row is None else _to_run(row)

    async def save(self, run: AgentRun, expected_version: int) -> None:
        async with self._sessions.begin() as session:
            row = await session.get(AgentRunRow, run.run_id, with_for_update=True)
            if row is None or row.version != expected_version:
                raise RuntimeError("AgentRun version conflict")
            row.status = run.status.value
            row.step = run.step
            row.observations = run.observations
            row.final_content = run.final_content
            row.failure_class = run.failure_class
            if run.updated_at is None:
                raise ValueError("AgentRun updated_at is required")
            row.updated_at = run.updated_at
            row.version = expected_version + 1

    async def record_tool_call(
        self,
        run_id: UUID,
        call_id: str,
        tool_name: str,
        arguments_hash: str,
        observation: dict[str, object],
        now: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(AgentToolCallRow)
                .values(
                    run_id=run_id,
                    call_id=call_id,
                    tool_name=tool_name,
                    arguments_hash=arguments_hash,
                    observation=observation,
                    created_at=now,
                )
                .on_conflict_do_nothing()
            )


def _to_run(row: AgentRunRow) -> AgentRun:
    return AgentRun(
        row.run_id,
        row.inbox_item_id,
        row.user_id,
        row.source_type,
        AgentRunStatus(row.status),
        row.step,
        list(row.observations),
        row.final_content,
        row.failure_class,
        row.created_at,
        row.updated_at,
        row.version,
    )
