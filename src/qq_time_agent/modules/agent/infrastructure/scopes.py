"""PostgreSQL Agent context scope persistence (conversation and event case)."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from qq_time_agent.modules.agent.contracts import AgentRunStatus, ContextScope, ScopedAgentReply
from qq_time_agent.modules.agent.infrastructure.tables import (
    AgentRunRow,
    ContextItemRow,
    ConversationRow,
    EventCaseRow,
)


class SqlAgentContextScopes:
    """Scope bookkeeping shared by the AgentRun repository implementation."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

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
        self, scope_id: UUID, scope_type: str, exclude_id: UUID, before: datetime, limit: int
    ) -> tuple[UUID, ...]:
        async with self._sessions() as session:
            values = await session.scalars(
                select(ContextItemRow.inbox_item_id)
                .where(
                    and_(
                        ContextItemRow.scope_id == scope_id,
                        ContextItemRow.scope_type == scope_type,
                        ContextItemRow.inbox_item_id != exclude_id,
                        ContextItemRow.occurred_at < before,
                    )
                )
                .order_by(ContextItemRow.occurred_at.desc())
                .limit(limit)
            )
            return tuple(values)

    async def list_final_replies(
        self, scope_id: UUID, scope_type: str, before: datetime, limit: int
    ) -> tuple[ScopedAgentReply, ...]:
        scope_condition = _scope_run_condition(scope_id, scope_type)
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AgentRunRow)
                .where(
                    and_(
                        scope_condition,
                        AgentRunRow.status == AgentRunStatus.COMPLETED.value,
                        AgentRunRow.final_content.is_not(None),
                        AgentRunRow.updated_at < before,
                    )
                )
                .order_by(AgentRunRow.updated_at.desc(), AgentRunRow.run_id)
                .limit(limit)
            )
            return tuple(
                ScopedAgentReply(row.run_id, row.final_content, row.updated_at)
                for row in rows
                if row.final_content is not None
            )


def _scope_run_condition(scope_id: UUID, scope_type: str) -> ColumnElement[bool]:
    if scope_type == "conversation":
        return AgentRunRow.conversation_id == scope_id
    if scope_type == "event":
        return AgentRunRow.event_case_id == scope_id
    raise ValueError("Agent context scope type is invalid")


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
