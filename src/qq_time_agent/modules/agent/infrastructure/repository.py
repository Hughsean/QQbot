"""PostgreSQL AgentRun repository with Inbox-level idempotency."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agent.contracts import (
    AgentRun,
    AgentRunStatus,
    ContextScope,
)
from qq_time_agent.modules.agent.infrastructure.tables import (
    AgentRunRow,
    AgentToolCallRow,
    ContextItemRow,
    ConversationRow,
    EventCaseRow,
)


class SqlAgentRunRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_or_create(
        self,
        inbox_item_id: UUID,
        user_id: str,
        source_type: str,
        now: datetime,
        scope: ContextScope | None = None,
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
            "conversation_id": None if scope is None else scope.conversation_id,
            "event_case_id": None if scope is None else scope.event_case_id,
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

    async def ensure_scope(
        self,
        user_id: str,
        conversation_key: str | None,
        event_key: str | None,
        now: datetime,
    ) -> ContextScope:
        conversation_id = None
        event_case_id = None
        async with self._sessions.begin() as session:
            if conversation_key:
                conversation_id = await _ensure_conversation(
                    session, user_id, conversation_key, now
                )
            if event_key:
                event_case_id = await _ensure_event_case(session, user_id, event_key, now)
        return ContextScope(conversation_id, event_case_id)

    async def attach_item(
        self, scope: ContextScope, inbox_item_id: UUID, occurred_at: datetime
    ) -> None:
        async with self._sessions.begin() as session:
            for scope_type, scope_id in (
                ("conversation", scope.conversation_id),
                ("event", scope.event_case_id),
            ):
                if scope_id is not None:
                    await session.execute(
                        insert(ContextItemRow)
                        .values(
                            scope_type=scope_type,
                            scope_id=scope_id,
                            inbox_item_id=inbox_item_id,
                            occurred_at=occurred_at,
                        )
                        .on_conflict_do_nothing()
                    )

    async def list_item_ids(
        self, scope_id: UUID, scope_type: str, exclude_id: UUID, limit: int
    ) -> tuple[UUID, ...]:
        async with self._sessions() as session:
            values = await session.scalars(
                select(ContextItemRow.inbox_item_id)
                .where(
                    and_(
                        ContextItemRow.scope_id == scope_id,
                        ContextItemRow.scope_type == scope_type,
                        ContextItemRow.inbox_item_id != exclude_id,
                    )
                )
                .order_by(ContextItemRow.occurred_at.desc())
                .limit(limit)
            )
            return tuple(values)

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
        row.conversation_id,
        row.event_case_id,
    )


async def _ensure_conversation(
    session: AsyncSession, user_id: str, key: str, now: datetime
) -> UUID:
    value = await session.scalar(
        insert(ConversationRow)
        .values(
            conversation_id=uuid4(),
            user_id=user_id,
            channel="owner",
            conversation_key=key,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_agent_conversation_scope")
        .returning(ConversationRow.conversation_id)
    )
    if value is not None:
        return value
    result = await session.scalar(
        select(ConversationRow.conversation_id).where(
            ConversationRow.user_id == user_id,
            ConversationRow.channel == "owner",
            ConversationRow.conversation_key == key,
        )
    )
    if result is None:
        raise RuntimeError("conversation scope creation lost row")
    return result


async def _ensure_event_case(session: AsyncSession, user_id: str, key: str, now: datetime) -> UUID:
    value = await session.scalar(
        insert(EventCaseRow)
        .values(
            event_case_id=uuid4(),
            user_id=user_id,
            event_key=key,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_agent_event_scope")
        .returning(EventCaseRow.event_case_id)
    )
    if value is not None:
        return value
    result = await session.scalar(
        select(EventCaseRow.event_case_id).where(
            EventCaseRow.user_id == user_id, EventCaseRow.event_key == key
        )
    )
    if result is None:
        raise RuntimeError("event scope creation lost row")
    return result
