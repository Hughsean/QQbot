"""PostgreSQL unified conversation timeline event repository."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agent.contracts import (
    ConversationEvent,
    ConversationEventView,
    ConversationScopeType,
    ConversationSnapshot,
    ConversationSummaryCandidate,
    ConversationSummaryView,
    ConversationSummaryWrite,
    snapshot_hash,
)
from qq_time_agent.modules.agent.infrastructure.conversation_summary_persistence import (
    list_summaries as list_persisted_summaries,
)
from qq_time_agent.modules.agent.infrastructure.conversation_summary_persistence import (
    list_summary_candidates as list_persisted_summary_candidates,
)
from qq_time_agent.modules.agent.infrastructure.conversation_summary_persistence import (
    write_summary as write_persisted_summary,
)
from qq_time_agent.modules.agent.infrastructure.conversation_views import event_view
from qq_time_agent.modules.agent.infrastructure.tables import (
    ConversationEventRow,
    ConversationSequenceRow,
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
        return tuple(event_view(row) for row in reversed(rows))

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
        return await list_persisted_summaries(
            self._sessions,
            user_id,
            scope_type,
            scope_id,
            max_sequence=max_sequence,
            limit=limit,
        )

    async def list_summary_candidates(
        self, user_id: str, *, protected_turns: int = 8, limit: int = 20
    ) -> tuple[ConversationSummaryCandidate, ...]:
        return await list_persisted_summary_candidates(
            self._sessions,
            user_id,
            protected_turns=protected_turns,
            limit=limit,
        )

    async def write_summary(self, request: ConversationSummaryWrite) -> ConversationSummaryView:
        return await write_persisted_summary(self._sessions, request)


async def append_timeline_event(
    session: AsyncSession, event: ConversationEvent, now: datetime
) -> ConversationEventView:
    """Idempotently append one event inside the caller's transaction."""
    await _lock_sequence_counter(session, event.user_id)
    existing = await _find_by_key(session, event.idempotency_key)
    if existing is not None:
        return event_view(existing)
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
    return event_view(stored)


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
