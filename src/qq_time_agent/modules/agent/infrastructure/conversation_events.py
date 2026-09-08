"""PostgreSQL unified conversation timeline event repository."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agent.contracts import (
    ConversationDeliveryStatus,
    ConversationEvent,
    ConversationEventRole,
    ConversationEventType,
    ConversationEventView,
    ConversationScopeType,
    ConversationSnapshot,
    ConversationSummaryView,
    ToolObservation,
    bounded_event_content,
    snapshot_hash,
)
from qq_time_agent.modules.agent.infrastructure.tables import (
    AgentRunRow,
    ConversationEventRow,
    ConversationSequenceRow,
    ConversationSummaryRow,
)

_LIMIT_MAX = 500


class SqlConversationEventRepository:
    """Append-only timeline with per-user monotonic sequence allocation.

    Sequences come from an atomic counter upsert holding a row lock until
    commit, so concurrent writers serialize and never compute ``max()+1``.
    Every scope of one user shares the counter, which makes merged timelines
    sortable by a single sequence space.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(self, event: ConversationEvent, now: datetime) -> ConversationEventView:
        async with self._sessions.begin() as session:
            return await append_timeline_event(session, event, now)

    async def current_sequence(self, user_id: str) -> int:
        async with self._sessions() as session:
            value = await session.scalar(
                select(ConversationSequenceRow.last_sequence).where(
                    ConversationSequenceRow.user_id == user_id
                )
            )
        return int(value or 0)

    async def list_timeline(
        self,
        user_id: str,
        scope_type: ConversationScopeType,
        scope_id: UUID,
        *,
        max_sequence: int | None = None,
        limit: int = 50,
    ) -> tuple[ConversationEventView, ...]:
        if not 1 <= limit <= _LIMIT_MAX:
            raise ValueError("conversation timeline limit must be between 1 and 500")
        if max_sequence is not None and max_sequence < 0:
            raise ValueError("conversation timeline sequence bound cannot be negative")
        conditions = [
            ConversationEventRow.user_id == user_id,
            ConversationEventRow.scope_type == scope_type.value,
            ConversationEventRow.scope_id == scope_id,
        ]
        if max_sequence is not None:
            conditions.append(ConversationEventRow.sequence <= max_sequence)
        async with self._sessions() as session:
            rows = tuple(
                await session.scalars(
                    select(ConversationEventRow)
                    .where(*conditions)
                    .order_by(ConversationEventRow.sequence.desc())
                    .limit(limit)
                )
            )
        return tuple(_view(row) for row in reversed(rows))

    async def create_snapshot(self, user_id: str, scope_id: UUID) -> ConversationSnapshot:
        """Pin the timeline read without allocating a sequence."""
        max_sequence = await self.current_sequence(user_id)
        return ConversationSnapshot(
            user_id=user_id,
            scope_id=scope_id,
            revision=max_sequence,
            max_sequence=max_sequence,
            context_hash=snapshot_hash(user_id, scope_id, max_sequence),
        )

    async def list_snapshot_events(
        self,
        user_id: str,
        scope_type: ConversationScopeType,
        scope_id: UUID,
        *,
        max_sequence: int,
        limit: int,
    ) -> tuple[ConversationEventView, ...]:
        return await self.list_timeline(
            user_id, scope_type, scope_id, max_sequence=max_sequence, limit=limit
        )

    async def list_summaries(
        self,
        user_id: str,
        scope_type: ConversationScopeType,
        scope_id: UUID,
        *,
        max_sequence: int,
        limit: int = 2,
    ) -> tuple[ConversationSummaryView, ...]:
        if not 1 <= limit <= 20:
            raise ValueError("conversation summary limit must be between 1 and 20")
        async with self._sessions() as session:
            rows = tuple(
                await session.scalars(
                    select(ConversationSummaryRow)
                    .where(
                        ConversationSummaryRow.user_id == user_id,
                        ConversationSummaryRow.scope_type == scope_type.value,
                        ConversationSummaryRow.scope_id == scope_id,
                        ConversationSummaryRow.to_sequence <= max_sequence,
                    )
                    .order_by(ConversationSummaryRow.to_sequence.desc())
                    .limit(limit)
                )
            )
        return tuple(_summary_view(row) for row in reversed(rows))


async def append_timeline_event(
    session: AsyncSession, event: ConversationEvent, now: datetime
) -> ConversationEventView:
    """Idempotently append one event inside the caller's transaction."""
    await _lock_sequence_counter(session, event.user_id)
    existing = await _find_by_key(session, event.idempotency_key)
    if existing is not None:
        return _view(existing)
    sequence = await _next_sequence(session, event.user_id)
    await session.execute(
        insert(ConversationEventRow)
        .values(
            event_id=event.event_id,
            scope_type=event.scope_type.value,
            scope_id=event.scope_id,
            user_id=event.user_id,
            sequence=sequence,
            event_type=event.event_type.value,
            role=event.role.value,
            occurred_at=event.occurred_at,
            created_at=now,
            content=event.content,
            content_ref=event.content_ref or None,
            content_hash=event.content_hash,
            delivery_status=None if event.delivery_status is None else event.delivery_status.value,
            run_id=event.run_id,
            inbox_item_id=event.inbox_item_id,
            notification_intent_id=event.notification_intent_id,
            idempotency_key=event.idempotency_key,
            metadata_json=dict(event.metadata),
        )
        .on_conflict_do_nothing(constraint="uq_agent_conversation_events_idempotency")
    )
    stored = await _find_by_key(session, event.idempotency_key)
    if stored is None:
        raise RuntimeError("conversation event idempotent insert lost stored row")
    return _view(stored)


def build_agent_reply_event(
    run: AgentRunRow, delivery: str, now: datetime
) -> ConversationEvent | None:
    """Immutable AGENT_REPLY event for the run's conversation scope."""
    if run.conversation_id is None:
        return None
    content = run.final_content or ""
    if not content.strip():
        return None
    return ConversationEvent(
        scope_type=ConversationScopeType.CONVERSATION,
        scope_id=run.conversation_id,
        user_id=run.user_id,
        event_type=ConversationEventType.AGENT_REPLY,
        occurred_at=now,
        content=bounded_event_content(content),
        idempotency_key=f"agent-reply:{run.run_id}",
        run_id=run.run_id,
        content_ref=f"agent-run:{run.run_id}",
        metadata={"delivery": delivery, "source_type": run.source_type},
    )


def build_tool_events(
    run: AgentRunRow, observation: ToolObservation, now: datetime
) -> tuple[ConversationEvent, ...]:
    """TOOL_CALL plus TOOL_RESULT events for the run's conversation scope."""
    if run.conversation_id is None:
        return ()
    output = bounded_event_content(observation_token_text(observation))
    common = {
        "tool": observation.name,
        "call_id": observation.call_id,
        "arguments_hash": observation.arguments_hash,
        "is_error": observation.is_error,
    }
    call = ConversationEvent(
        scope_type=ConversationScopeType.CONVERSATION,
        scope_id=run.conversation_id,
        user_id=run.user_id,
        event_type=ConversationEventType.TOOL_CALL,
        occurred_at=now,
        content=bounded_event_content(
            f"tool {observation.name} call {observation.call_id} "
            f"arguments_sha256 {observation.arguments_hash}"
        ),
        idempotency_key=f"tool-call:{run.run_id}:{observation.call_id}",
        run_id=run.run_id,
        metadata=common,
    )
    result = ConversationEvent(
        scope_type=ConversationScopeType.CONVERSATION,
        scope_id=run.conversation_id,
        user_id=run.user_id,
        event_type=ConversationEventType.TOOL_RESULT,
        occurred_at=now,
        content=output,
        idempotency_key=f"tool-result:{run.run_id}:{observation.call_id}",
        run_id=run.run_id,
        content_ref=f"agent-tool-call:{observation.call_id}",
        metadata=common,
    )
    return (call, result)


def observation_token_text(observation: ToolObservation) -> str:
    if isinstance(observation.output, str):
        return observation.output
    return str(observation.output)


async def _lock_sequence_counter(session: AsyncSession, user_id: str) -> None:
    """Serialize idempotency lookup and allocation for one user's sequence space."""
    await session.execute(
        insert(ConversationSequenceRow)
        .values(user_id=user_id, last_sequence=0)
        .on_conflict_do_nothing(index_elements=[ConversationSequenceRow.user_id])
    )
    counter = await session.scalar(
        select(ConversationSequenceRow)
        .where(ConversationSequenceRow.user_id == user_id)
        .with_for_update()
    )
    if counter is None:
        raise RuntimeError("conversation sequence counter is missing")


async def _next_sequence(session: AsyncSession, user_id: str) -> int:
    value = await session.scalar(
        insert(ConversationSequenceRow)
        .values(user_id=user_id, last_sequence=1)
        .on_conflict_do_update(
            index_elements=[ConversationSequenceRow.user_id],
            set_={"last_sequence": ConversationSequenceRow.last_sequence + 1},
        )
        .returning(ConversationSequenceRow.last_sequence)
    )
    if value is None:
        raise RuntimeError("conversation sequence allocation failed")
    return int(value)


async def _find_by_key(session: AsyncSession, idempotency_key: str) -> ConversationEventRow | None:
    value: ConversationEventRow | None = await session.scalar(
        select(ConversationEventRow).where(ConversationEventRow.idempotency_key == idempotency_key)
    )
    return value


def _view(row: ConversationEventRow) -> ConversationEventView:
    return ConversationEventView(
        event_id=row.event_id,
        scope_type=ConversationScopeType(row.scope_type),
        scope_id=row.scope_id,
        user_id=row.user_id,
        sequence=row.sequence,
        event_type=ConversationEventType(row.event_type),
        role=ConversationEventRole(row.role),
        occurred_at=row.occurred_at,
        created_at=row.created_at,
        content=row.content,
        content_ref=row.content_ref or "",
        content_hash=row.content_hash,
        delivery_status=None
        if row.delivery_status is None
        else ConversationDeliveryStatus(row.delivery_status),
        run_id=row.run_id,
        inbox_item_id=row.inbox_item_id,
        notification_intent_id=row.notification_intent_id,
        idempotency_key=row.idempotency_key,
        metadata=dict(row.metadata_json),
    )


def _summary_view(row: ConversationSummaryRow) -> ConversationSummaryView:
    return ConversationSummaryView(
        summary_id=row.summary_id,
        user_id=row.user_id,
        scope_type=ConversationScopeType(row.scope_type),
        scope_id=row.scope_id,
        from_sequence=row.from_sequence,
        to_sequence=row.to_sequence,
        summary_text=row.content,
        source_hash=row.source_hash,
        facts=_summary_values(row.structured_json, "facts"),
        decisions=_summary_values(row.structured_json, "decisions"),
        commitments=_summary_values(row.structured_json, "commitments"),
        open_loops=_summary_values(row.structured_json, "open_loops"),
        preferences=_summary_values(row.structured_json, "preferences"),
        time_anchors=_summary_values(row.structured_json, "time_anchors"),
        tool_side_effects=_summary_values(row.structured_json, "tool_side_effects"),
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
    )


def _summary_values(data: dict[str, object], key: str) -> tuple[str, ...]:
    value = data.get(key, ())
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))
