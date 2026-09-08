"""Unified timeline context assembly with pinned snapshots and protected turns."""

import logging
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from qq_time_agent.modules.agent.contracts import (
    ContextDiagnostics,
    ConversationContextRepository,
    ConversationEventType,
    ConversationEventView,
    ConversationScopeType,
    ConversationSnapshot,
    ConversationSummaryView,
    owner_timeline_scope_id,
)
from qq_time_agent.modules.ai_gateway.contracts import AgentMessage, AgentMessageRole

LOGGER = logging.getLogger(__name__)

_MESSAGE_ROLE: dict[ConversationEventType, AgentMessageRole] = {
    ConversationEventType.USER_MESSAGE: AgentMessageRole.USER,
    ConversationEventType.AGENT_REPLY: AgentMessageRole.ASSISTANT,
    ConversationEventType.TOOL_CALL: AgentMessageRole.TOOL,
    ConversationEventType.TOOL_RESULT: AgentMessageRole.TOOL,
    ConversationEventType.MAIL_NOTIFICATION: AgentMessageRole.TOOL,
    ConversationEventType.MAIL_DIGEST: AgentMessageRole.TOOL,
    ConversationEventType.DAILY_DIGEST: AgentMessageRole.TOOL,
    ConversationEventType.SYSTEM_RESULT: AgentMessageRole.TOOL,
}

_SUMMARY_EVENT_LABEL = "CONVERSATION_SUMMARY"


@dataclass(frozen=True, slots=True)
class TimelineContext:
    """Pinned timeline read projected into provider-neutral messages."""

    snapshot: ConversationSnapshot
    messages: tuple[AgentMessage, ...]
    diagnostics: tuple[ContextDiagnostics, ...]


class TimelineContextAssembler:
    """Merge the conversation and owner timelines into a stable message list.

    Model input order is fixed: older summaries, older selected events,
    recent complete turns, then recent notifications. The current turn
    (its user message and tool observations) is excluded here because it
    travels with the live request payload, never duplicated from history.
    """

    def __init__(
        self,
        repository: ConversationContextRepository,
        protected_turns: int = 8,
        notification_limit: int = 10,
        older_event_limit: int = 16,
        summary_limit: int = 2,
        read_limit: int = 200,
        hard_char_limit: int = 60_000,
    ) -> None:
        if not 6 <= protected_turns <= 12:
            raise ValueError("timeline protected turns must be between 6 and 12")
        positive = (notification_limit, older_event_limit, summary_limit, read_limit)
        if any(value < 1 for value in positive) or hard_char_limit < 10_000:
            raise ValueError("timeline context limits are invalid")
        if read_limit < protected_turns * 4:
            raise ValueError("timeline read limit cannot cover the protected turns")
        self._repository = repository
        self._protected_turns = protected_turns
        self._notification_limit = notification_limit
        self._older_event_limit = older_event_limit
        self._summary_limit = summary_limit
        self._read_limit = read_limit
        self._hard_char_limit = hard_char_limit

    async def build(
        self,
        user_id: str,
        conversation_id: UUID,
        *,
        current_run_id: UUID | None = None,
        current_inbox_item_id: UUID | None = None,
        snapshot: ConversationSnapshot | None = None,
    ) -> TimelineContext:
        snapshot = snapshot or await self._repository.create_snapshot(user_id, conversation_id)
        visible = await self._visible_events(user_id, conversation_id, snapshot)
        visible = [
            event
            for event in visible
            if not (current_run_id is not None and event.run_id == current_run_id)
            and not (
                current_inbox_item_id is not None
                and event.event_type is ConversationEventType.USER_MESSAGE
                and event.inbox_item_id == current_inbox_item_id
            )
        ]
        protected_start = _protected_start(visible, self._protected_turns)
        protected = visible[protected_start:]
        older_all = visible[:protected_start]
        older = older_all[-self._older_event_limit :]
        notifications_all = [
            item for item in protected if item.scope_type is ConversationScopeType.OWNER_TIMELINE
        ]
        notifications = notifications_all[-self._notification_limit :]
        turns = _split_turns(
            [item for item in protected if item.scope_type is ConversationScopeType.CONVERSATION]
        )
        summaries = list(
            await self._repository.list_summaries(
                user_id,
                ConversationScopeType.CONVERSATION,
                conversation_id,
                max_sequence=snapshot.max_sequence,
                limit=self._summary_limit,
            )
        )
        diagnostics = _bounded_diagnostics(
            len(older_all) - len(older), len(notifications_all) - len(notifications)
        )
        diagnostics.extend(
            _bound_regions(turns, notifications, older, summaries, self._hard_char_limit)
        )
        for item in diagnostics:
            if item.kind == "protected-turns-truncated":
                LOGGER.warning(
                    "Agent 时间线保护区超出硬限制: 已截断最早轮次并保留最近轮次",
                    extra={"role": "agent", "kind": item.kind, "detail": item.detail},
                )
        messages = [
            *(_summary_message(item) for item in summaries),
            *(_older_message(item) for item in older),
            *(
                _turn_message(item) if item.scope_type is ConversationScopeType.CONVERSATION
                else _notification_message(item)
                for item in sorted(
                    (*_flatten(turns), *notifications), key=lambda item: item.sequence
                )
            ),
        ]
        diagnostics.append(_selection_diagnostics(snapshot, visible, messages))
        return TimelineContext(snapshot, tuple(messages), tuple(diagnostics))

    async def _visible_events(
        self, user_id: str, conversation_id: UUID, snapshot: ConversationSnapshot
    ) -> list[ConversationEventView]:
        conversation = await self._repository.list_snapshot_events(
            user_id,
            ConversationScopeType.CONVERSATION,
            conversation_id,
            max_sequence=snapshot.max_sequence,
            limit=self._read_limit,
        )
        owner = await self._repository.list_snapshot_events(
            user_id,
            ConversationScopeType.OWNER_TIMELINE,
            owner_timeline_scope_id(user_id),
            max_sequence=snapshot.max_sequence,
            limit=self._read_limit,
        )
        merged = {event.event_id: event for event in (*conversation, *owner)}
        return sorted(merged.values(), key=lambda event: event.sequence)


def _protected_start(events: list[ConversationEventView], protected_turns: int) -> int:
    """Index opening the K-th-from-last complete turn."""
    replies = [
        index
        for index, event in enumerate(events)
        if event.event_type is ConversationEventType.AGENT_REPLY
    ]
    if len(replies) < protected_turns:
        return 0
    reply_index = replies[-protected_turns]
    for index in range(reply_index, -1, -1):
        if events[index].event_type is ConversationEventType.USER_MESSAGE:
            return index
        if index != reply_index and events[index].event_type is ConversationEventType.AGENT_REPLY:
            return index + 1
    return reply_index


def _split_turns(events: list[ConversationEventView]) -> list[list[ConversationEventView]]:
    """Group conversation events into user-message-to-reply turns."""
    turns: list[list[ConversationEventView]] = []
    current: list[ConversationEventView] = []
    for event in events:
        if event.event_type is ConversationEventType.USER_MESSAGE and current:
            turns.append(current)
            current = []
        current.append(event)
        if event.event_type is ConversationEventType.AGENT_REPLY:
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns


def _bounded_diagnostics(older_dropped: int, notification_dropped: int) -> list[ContextDiagnostics]:
    diagnostics: list[ContextDiagnostics] = []
    if older_dropped > 0:
        diagnostics.append(
            ContextDiagnostics("older-events-bounded", f"dropped_events={older_dropped}")
        )
    if notification_dropped > 0:
        diagnostics.append(
            ContextDiagnostics("notifications-bounded", f"dropped_events={notification_dropped}")
        )
    return diagnostics


def _bound_regions(
    turns: list[list[ConversationEventView]],
    notifications: list[ConversationEventView],
    older: list[ConversationEventView],
    summaries: list[ConversationSummaryView],
    hard_char_limit: int,
) -> list[ContextDiagnostics]:
    """Drop the lowest-value regions first when the hard char limit is hit."""
    diagnostics: list[ContextDiagnostics] = []
    while _region_chars(turns, notifications, older, summaries) > hard_char_limit:
        if older:
            older.pop(0)
            diagnostics.append(ContextDiagnostics("older-events-dropped", "dropped_events=1"))
            continue
        if summaries:
            summaries.pop(0)
            diagnostics.append(ContextDiagnostics("summaries-dropped", "dropped_summaries=1"))
            continue
        if notifications:
            notifications.pop(0)
            diagnostics.append(ContextDiagnostics("notifications-dropped", "dropped_events=1"))
            continue
        if len(turns) > 1:
            dropped = turns.pop(0)
            diagnostics.append(
                ContextDiagnostics(
                    "protected-turns-truncated",
                    f"dropped_events={len(dropped)} remaining_turns={len(turns)}",
                )
            )
            continue
        break
    return diagnostics


def _region_chars(
    turns: list[list[ConversationEventView]],
    notifications: list[ConversationEventView],
    older: list[ConversationEventView],
    summaries: list[ConversationSummaryView],
) -> int:
    return (
        sum(len(item.content) for item in _flatten(turns))
        + sum(len(item.content) for item in notifications)
        + sum(len(item.content) for item in older)
        + sum(len(item.summary_text) for item in summaries)
    )


def _flatten(turns: list[list[ConversationEventView]]) -> list[ConversationEventView]:
    return [event for turn in turns for event in turn]


def _turn_message(event: ConversationEventView) -> AgentMessage:
    return AgentMessage(
        role=_MESSAGE_ROLE[event.event_type],
        content=event.content,
        event_id=event.event_id,
        event_type=event.event_type.value,
    )


def _notification_message(event: ConversationEventView) -> AgentMessage:
    status = "" if event.delivery_status is None else f" {event.delivery_status.value}"
    return AgentMessage(
        role=AgentMessageRole.TOOL,
        content=f"[external-event {event.event_type.value}{status}]\n{event.content}",
        event_id=event.event_id,
        event_type=event.event_type.value,
        delivery_status=None if event.delivery_status is None else event.delivery_status.value,
    )


def _selection_diagnostics(
    snapshot: ConversationSnapshot,
    events: list[ConversationEventView],
    messages: list[AgentMessage],
) -> ContextDiagnostics:
    selected_ids = _message_events(messages)
    selected = Counter(
        item.event_type.value for item in events if item.event_id in selected_ids
    )
    detail = (
        f"scope={_scope_hash(snapshot.scope_id)} max_sequence={snapshot.max_sequence} "
        f"sequence_range={_sequence_range(events)} selected={len(messages)} "
        f"dropped={max(0, len(events) - len(selected_ids))} "
        f"token_count={sum(_message_tokens(item) for item in messages)} "
        f"types={','.join(f'{key}:{value}' for key, value in sorted(selected.items()))} "
        f"context_hash={snapshot.context_hash}"
    )
    return ContextDiagnostics("timeline-selection", detail)


def _message_events(messages: list[AgentMessage]) -> set[UUID]:
    return {item.event_id for item in messages if item.event_id is not None}


def _message_tokens(message: AgentMessage) -> int:
    from qq_time_agent.modules.ai_gateway.contracts import estimate_tokens

    return estimate_tokens(message.content)


def _scope_hash(scope_id: UUID) -> str:
    return sha256(str(scope_id).encode()).hexdigest()[:12]


def _sequence_range(events: list[ConversationEventView]) -> str:
    if not events:
        return "none"
    return f"{events[0].sequence}-{events[-1].sequence}"


def _older_message(event: ConversationEventView) -> AgentMessage:
    return AgentMessage(
        role=_MESSAGE_ROLE[event.event_type],
        content=f"[history-event {event.event_type.value}]\n{event.content}",
        event_id=event.event_id,
        event_type=event.event_type.value,
    )


def _summary_message(summary: ConversationSummaryView) -> AgentMessage:
    return AgentMessage(
        role=AgentMessageRole.SYSTEM,
        content=(
            f"[{_SUMMARY_EVENT_LABEL} {summary.from_sequence}-{summary.to_sequence}]\n"
            + summary.summary_text
        ),
        event_type=_SUMMARY_EVENT_LABEL,
    )
