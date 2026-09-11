"""PostgreSQL persistence operations for layered conversation summaries."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agent.contracts import (
    ConversationEventView,
    ConversationScopeType,
    ConversationSummaryCandidate,
    ConversationSummaryView,
    ConversationSummaryWrite,
)
from qq_time_agent.modules.agent.infrastructure.conversation_views import (
    event_view,
    structured_summary,
    summary_matches,
    summary_view,
)
from qq_time_agent.modules.agent.infrastructure.tables import (
    ConversationEventRow,
    ConversationSummaryRow,
)


async def list_summaries(
    sessions: async_sessionmaker[AsyncSession],
    user_id: str,
    scope_type: ConversationScopeType,
    scope_id: UUID,
    *,
    max_sequence: int,
    limit: int,
) -> tuple[ConversationSummaryView, ...]:
    if not 1 <= limit <= 20:
        raise ValueError("conversation summary limit must be between 1 and 20")
    async with sessions() as session:
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
    return tuple(summary_view(row) for row in reversed(rows))


async def list_summary_candidates(
    sessions: async_sessionmaker[AsyncSession],
    user_id: str,
    *,
    protected_turns: int,
    limit: int,
) -> tuple[ConversationSummaryCandidate, ...]:
    if not 1 <= protected_turns <= 12 or not 1 <= limit <= 100:
        raise ValueError("summary candidate limits are invalid")
    event_rows, summary_rows = await _candidate_rows(sessions, user_id)
    covered = {(row.scope_id, row.from_sequence, row.to_sequence) for row in summary_rows}
    grouped: dict[UUID, list[ConversationEventRow]] = {}
    for row in event_rows:
        grouped.setdefault(row.scope_id, []).append(row)
    candidates = _uncovered_candidates(user_id, grouped, covered, protected_turns)
    candidates.sort(key=lambda item: (item.scope_id.hex, item.to_sequence))
    return tuple(candidates[:limit])


async def write_summary(
    sessions: async_sessionmaker[AsyncSession], request: ConversationSummaryWrite
) -> ConversationSummaryView:
    """Persist one verified summary without replacing source events."""
    summary = request.summary
    async with sessions.begin() as session:
        await _lock_summary_scope(session, request)
        source = await _source_events(session, request)
        if source != request.source_events:
            raise ValueError("conversation summary source events changed")
        existing = await _summary_by_key(session, summary.idempotency_key)
        if existing is not None:
            if not summary_matches(existing, summary):
                raise ValueError("conversation summary idempotency key changed")
            return summary_view(existing)
        if await _overlapping_summary(session, request) is not None:
            raise ValueError("conversation summary source range overlaps")
        await _insert_summary(session, request)
        stored = await _summary_by_key(session, summary.idempotency_key)
        if stored is None:
            raise RuntimeError("conversation summary idempotent insert lost stored row")
        return summary_view(stored)


async def _lock_summary_scope(session: AsyncSession, request: ConversationSummaryWrite) -> None:
    summary = request.summary
    scope_key = f"{summary.user_id}:{summary.scope_type.value}:{summary.scope_id}"
    await session.scalar(select(func.pg_advisory_xact_lock(func.hashtextextended(scope_key, 0))))


async def _candidate_rows(
    sessions: async_sessionmaker[AsyncSession], user_id: str
) -> tuple[tuple[ConversationEventRow, ...], tuple[ConversationSummaryRow, ...]]:
    async with sessions() as session:
        events = tuple(
            await session.scalars(
                select(ConversationEventRow)
                .where(
                    ConversationEventRow.user_id == user_id,
                    ConversationEventRow.scope_type == ConversationScopeType.CONVERSATION.value,
                )
                .order_by(ConversationEventRow.scope_id, ConversationEventRow.sequence)
                .limit(5000)
            )
        )
        summaries = tuple(
            await session.scalars(
                select(ConversationSummaryRow).where(
                    ConversationSummaryRow.user_id == user_id,
                    ConversationSummaryRow.scope_type == ConversationScopeType.CONVERSATION.value,
                )
            )
        )
    return events, summaries


def _uncovered_candidates(
    user_id: str,
    grouped: dict[UUID, list[ConversationEventRow]],
    covered: set[tuple[UUID, int, int]],
    protected_turns: int,
) -> list[ConversationSummaryCandidate]:
    candidates: list[ConversationSummaryCandidate] = []
    for scope_id, rows in grouped.items():
        for from_sequence, to_sequence in _complete_turn_ranges(rows)[:-protected_turns]:
            if (scope_id, from_sequence, to_sequence) not in covered:
                candidates.append(
                    ConversationSummaryCandidate(user_id, scope_id, from_sequence, to_sequence)
                )
    return candidates


async def _source_events(
    session: AsyncSession, request: ConversationSummaryWrite
) -> tuple[ConversationEventView, ...]:
    summary = request.summary
    rows = tuple(
        await session.scalars(
            select(ConversationEventRow)
            .where(
                ConversationEventRow.user_id == summary.user_id,
                ConversationEventRow.scope_type == summary.scope_type.value,
                ConversationEventRow.scope_id == summary.scope_id,
                ConversationEventRow.sequence.between(summary.from_sequence, summary.to_sequence),
            )
            .order_by(ConversationEventRow.sequence)
        )
    )
    return tuple(event_view(row) for row in rows)


async def _summary_by_key(
    session: AsyncSession, idempotency_key: str
) -> ConversationSummaryRow | None:
    value: ConversationSummaryRow | None = await session.scalar(
        select(ConversationSummaryRow).where(
            ConversationSummaryRow.idempotency_key == idempotency_key
        )
    )
    return value


async def _overlapping_summary(
    session: AsyncSession, request: ConversationSummaryWrite
) -> ConversationSummaryRow | None:
    summary = request.summary
    value: ConversationSummaryRow | None = await session.scalar(
        select(ConversationSummaryRow).where(
            ConversationSummaryRow.user_id == summary.user_id,
            ConversationSummaryRow.scope_type == summary.scope_type.value,
            ConversationSummaryRow.scope_id == summary.scope_id,
            ConversationSummaryRow.from_sequence <= summary.to_sequence,
            ConversationSummaryRow.to_sequence >= summary.from_sequence,
        )
    )
    return value


async def _insert_summary(session: AsyncSession, request: ConversationSummaryWrite) -> None:
    summary = request.summary
    await session.execute(
        insert(ConversationSummaryRow)
        .values(
            summary_id=summary.summary_id,
            user_id=summary.user_id,
            scope_type=summary.scope_type.value,
            scope_id=summary.scope_id,
            summary_kind="timeline",
            from_sequence=summary.from_sequence,
            to_sequence=summary.to_sequence,
            content=summary.summary_text,
            content_hash=summary.source_hash,
            source_hash=summary.source_hash,
            structured_json=structured_summary(summary),
            idempotency_key=summary.idempotency_key,
            created_at=summary.created_at,
        )
        .on_conflict_do_nothing(constraint="uq_agent_conversation_summaries_idempotency")
    )


def _complete_turn_ranges(rows: list[ConversationEventRow]) -> list[tuple[int, int]]:
    turns: list[tuple[int, int]] = []
    start: int | None = None
    for row in rows:
        if row.event_type == "USER_MESSAGE" and start is None:
            start = row.sequence
        elif row.event_type == "AGENT_REPLY" and start is not None:
            turns.append((start, row.sequence))
            start = None
    return turns
