"""Deterministic, bounded timeline summary generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from uuid import NAMESPACE_URL, UUID, uuid5

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agent.contracts import (
    ConversationContextRepository,
    ConversationEventType,
    ConversationEventView,
    ConversationScopeType,
    ConversationSummaryView,
    ConversationSummaryWrite,
    summary_source_hash,
)

_SUMMARY_NAMESPACE = uuid5(NAMESPACE_URL, "qq-time-agent:conversation-summary:v1")
_MAX_SOURCE_EVENTS = 400
_MAX_FIELD_ITEMS = 12
_MAX_ITEM_CHARS = 240


@dataclass(frozen=True, slots=True)
class SummaryRequest:
    user_id: str
    scope_id: UUID
    from_sequence: int
    to_sequence: int


class ConversationSummaryService:
    """Create an idempotent summary only for one complete old turn range."""

    def __init__(self, repository: ConversationContextRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def summarize(self, request: SummaryRequest) -> ConversationSummaryView:
        if request.from_sequence < 1 or request.to_sequence < request.from_sequence:
            raise ValueError("summary sequence range is invalid")
        events = await self._repository.list_snapshot_events(
            request.user_id,
            ConversationScopeType.CONVERSATION,
            request.scope_id,
            max_sequence=request.to_sequence,
            limit=_MAX_SOURCE_EVENTS,
        )
        source = tuple(
            item for item in events if request.from_sequence <= item.sequence <= request.to_sequence
        )
        _validate_complete_turn(source, request)
        source_hash = summary_source_hash(source)
        summary = _make_summary(request, source, source_hash, self._clock.now())
        return await self._repository.write_summary(ConversationSummaryWrite(summary, source))


def _validate_complete_turn(
    events: tuple[ConversationEventView, ...], request: SummaryRequest
) -> None:
    if not events or events[0].event_type is not ConversationEventType.USER_MESSAGE:
        raise ValueError("summary must start with a user message")
    if events[-1].event_type is not ConversationEventType.AGENT_REPLY:
        raise ValueError("summary must end with an agent reply")
    if (events[0].sequence, events[-1].sequence) != (
        request.from_sequence,
        request.to_sequence,
    ):
        raise ValueError("summary source bounds do not match")
    if any(left.sequence >= right.sequence for left, right in pairwise(events)):
        raise ValueError("summary source sequence is not strictly increasing")
    if any(item.scope_type is not ConversationScopeType.CONVERSATION for item in events):
        raise ValueError("summary source scope is invalid")


def _make_summary(
    request: SummaryRequest,
    events: tuple[ConversationEventView, ...],
    source_hash: str,
    created_at: datetime,
) -> ConversationSummaryView:
    user_items = tuple(
        _clip(item.content)
        for item in events
        if item.event_type is ConversationEventType.USER_MESSAGE
    )
    reply_items = tuple(
        _clip(item.content)
        for item in events
        if item.event_type is ConversationEventType.AGENT_REPLY
    )
    tool_items = tuple(
        _clip(item.content)
        for item in events
        if item.event_type is ConversationEventType.TOOL_RESULT
    )
    text = (
        f"已压缩 {len(events)} 条事件 (sequence {request.from_sequence}-"
        f"{request.to_sequence}); 用户消息 {len(user_items)} 条, "
        f"Agent 回复 {len(reply_items)} 条, 工具结果 {len(tool_items)} 条。"
    )
    summary_id = uuid5(
        _SUMMARY_NAMESPACE,
        f"{request.user_id}:{request.scope_id}:{request.from_sequence}:{request.to_sequence}:{source_hash}",
    )
    return ConversationSummaryView(
        summary_id=summary_id,
        user_id=request.user_id,
        scope_type=ConversationScopeType.CONVERSATION,
        scope_id=request.scope_id,
        from_sequence=request.from_sequence,
        to_sequence=request.to_sequence,
        summary_text=text,
        created_at=created_at,
        source_hash=source_hash,
        facts=user_items[:_MAX_FIELD_ITEMS],
        decisions=reply_items[:_MAX_FIELD_ITEMS],
        tool_side_effects=tool_items[:_MAX_FIELD_ITEMS],
        idempotency_key=f"conversation-summary:{summary_id}",
    )


def _clip(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= _MAX_ITEM_CHARS:
        return normalized
    return normalized[: _MAX_ITEM_CHARS - 1] + "…"
