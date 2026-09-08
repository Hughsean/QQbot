"""Provider-neutral unified conversation timeline event contracts."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

_CONTENT_LIMIT = 12_000
_IDEMPOTENCY_LIMIT = 255
_CONTENT_REF_LIMIT = 160
_USER_ID_LIMIT = 120
_METADATA_LIMIT = 32


class ConversationEventType(StrEnum):
    USER_MESSAGE = "USER_MESSAGE"
    AGENT_REPLY = "AGENT_REPLY"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    MAIL_NOTIFICATION = "MAIL_NOTIFICATION"
    MAIL_DIGEST = "MAIL_DIGEST"
    DAILY_DIGEST = "DAILY_DIGEST"
    SYSTEM_RESULT = "SYSTEM_RESULT"


class ConversationScopeType(StrEnum):
    CONVERSATION = "conversation"
    OWNER_TIMELINE = "owner_timeline"


class ConversationEventRole(StrEnum):
    USER = "user"
    AGENT = "agent"
    TOOL = "tool"
    SYSTEM = "system"


class ConversationDeliveryStatus(StrEnum):
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


_NOTIFICATION_TYPES = frozenset(
    {
        ConversationEventType.MAIL_NOTIFICATION,
        ConversationEventType.MAIL_DIGEST,
        ConversationEventType.DAILY_DIGEST,
    }
)
_TIMELINE_NOTIFICATION_TYPES = _NOTIFICATION_TYPES | {ConversationEventType.SYSTEM_RESULT}

_ROLE_BY_TYPE: Mapping[ConversationEventType, ConversationEventRole] = {
    ConversationEventType.USER_MESSAGE: ConversationEventRole.USER,
    ConversationEventType.AGENT_REPLY: ConversationEventRole.AGENT,
    ConversationEventType.TOOL_CALL: ConversationEventRole.TOOL,
    ConversationEventType.TOOL_RESULT: ConversationEventRole.TOOL,
    ConversationEventType.MAIL_NOTIFICATION: ConversationEventRole.SYSTEM,
    ConversationEventType.MAIL_DIGEST: ConversationEventRole.SYSTEM,
    ConversationEventType.DAILY_DIGEST: ConversationEventRole.SYSTEM,
    ConversationEventType.SYSTEM_RESULT: ConversationEventRole.SYSTEM,
}

_SCOPE_BY_TYPE: Mapping[ConversationEventType, ConversationScopeType] = {
    ConversationEventType.USER_MESSAGE: ConversationScopeType.CONVERSATION,
    ConversationEventType.AGENT_REPLY: ConversationScopeType.CONVERSATION,
    ConversationEventType.TOOL_CALL: ConversationScopeType.CONVERSATION,
    ConversationEventType.TOOL_RESULT: ConversationScopeType.CONVERSATION,
    ConversationEventType.MAIL_NOTIFICATION: ConversationScopeType.OWNER_TIMELINE,
    ConversationEventType.MAIL_DIGEST: ConversationScopeType.OWNER_TIMELINE,
    ConversationEventType.DAILY_DIGEST: ConversationScopeType.OWNER_TIMELINE,
    ConversationEventType.SYSTEM_RESULT: ConversationScopeType.OWNER_TIMELINE,
}


def owner_timeline_scope_id(user_id: str) -> UUID:
    """Stable per-user owner timeline scope identity."""
    return uuid5(NAMESPACE_URL, f"agent-owner-timeline:{user_id}")


def is_notification_event(event_type: ConversationEventType) -> bool:
    return event_type in _NOTIFICATION_TYPES


def bounded_event_content(content: str) -> str:
    """Bound timeline content to the persistable event limit deterministically."""
    if len(content) <= _CONTENT_LIMIT:
        return content
    marker = "…[event-truncated]"
    return content[: _CONTENT_LIMIT - len(marker)] + marker


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    """Append-only unified timeline event write request."""

    scope_type: ConversationScopeType
    scope_id: UUID
    user_id: str
    event_type: ConversationEventType
    occurred_at: datetime
    content: str
    idempotency_key: str
    run_id: UUID | None = None
    inbox_item_id: UUID | None = None
    notification_intent_id: UUID | None = None
    delivery_status: ConversationDeliveryStatus | None = None
    content_ref: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if len(self.user_id) > _USER_ID_LIMIT or not self.user_id.strip():
            raise ValueError("conversation event user is required")
        if len(self.idempotency_key) > _IDEMPOTENCY_LIMIT or not self.idempotency_key.strip():
            raise ValueError("conversation event idempotency key is required")
        if not self.content.strip() or len(self.content) > _CONTENT_LIMIT:
            raise ValueError("conversation event content is required and bounded")
        if len(self.content_ref) > _CONTENT_REF_LIMIT:
            raise ValueError("conversation event content reference is too long")
        _require_aware(self.occurred_at, "occurred_at")
        if self.created_at is not None:
            _require_aware(self.created_at, "created_at")
        if len(self.metadata) > _METADATA_LIMIT:
            raise ValueError("conversation event metadata is too large")
        if any(not str(key).strip() for key in self.metadata):
            raise ValueError("conversation event metadata keys are required")
        _validate_references(self)
        _validate_scope(self)

    @property
    def role(self) -> ConversationEventRole:
        return _ROLE_BY_TYPE[self.event_type]

    @property
    def content_hash(self) -> str:
        return sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConversationEventView:
    """Read-only projection of a persisted conversation event."""

    event_id: UUID
    scope_type: ConversationScopeType
    scope_id: UUID
    user_id: str
    sequence: int
    event_type: ConversationEventType
    role: ConversationEventRole
    occurred_at: datetime
    created_at: datetime
    content: str
    content_ref: str
    content_hash: str
    delivery_status: ConversationDeliveryStatus | None
    run_id: UUID | None
    inbox_item_id: UUID | None
    notification_intent_id: UUID | None
    idempotency_key: str
    metadata: dict[str, object]

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("conversation event sequence must be positive")
        if len(self.content_hash) != 64:
            raise ValueError("conversation event content hash is invalid")


class ConversationEventRepository(Protocol):
    """Agent-owned append-only unified timeline persistence."""

    async def append(self, event: ConversationEvent, now: datetime) -> ConversationEventView: ...

    async def current_sequence(self, user_id: str) -> int:
        """Latest allocated sequence for the user's shared timeline space."""
        ...

    async def list_timeline(
        self,
        user_id: str,
        scope_type: ConversationScopeType,
        scope_id: UUID,
        *,
        max_sequence: int | None = None,
        limit: int = 50,
    ) -> tuple[ConversationEventView, ...]:
        """Most recent events in ascending sequence order for one scope."""
        ...


@dataclass(frozen=True, slots=True)
class ConversationSnapshot:
    """Immutable read pin over the user's shared timeline sequence space.

    ``revision`` is the snapshot epoch: under the per-user shared counter it
    numerically equals ``max_sequence``, because any committed append in any
    scope bumps the same counter. The distinct names keep the two roles
    separable if scopes ever diverge.
    """

    user_id: str
    scope_id: UUID
    revision: int
    max_sequence: int
    context_hash: str

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("conversation snapshot user is required")
        if self.revision < 0 or self.max_sequence < 0:
            raise ValueError("conversation snapshot sequence values are invalid")
        if len(self.context_hash) != 64:
            raise ValueError("conversation snapshot hash is invalid")


def snapshot_hash(user_id: str, scope_id: UUID, max_sequence: int) -> str:
    """Deterministic identity hash for one pinned timeline read."""
    return sha256(f"{user_id}:{scope_id}:{max_sequence}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ConversationSummaryView:
    """Read-only compressed view of a bounded timeline region."""

    summary_id: UUID
    user_id: str
    scope_type: ConversationScopeType
    scope_id: UUID
    from_sequence: int
    to_sequence: int
    summary_text: str
    created_at: datetime
    source_hash: str = ""
    facts: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    commitments: tuple[str, ...] = ()
    open_loops: tuple[str, ...] = ()
    preferences: tuple[str, ...] = ()
    time_anchors: tuple[str, ...] = ()
    tool_side_effects: tuple[str, ...] = ()
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        if self.from_sequence < 1 or self.to_sequence < self.from_sequence:
            raise ValueError("conversation summary sequence range is invalid")
        if not self.summary_text.strip():
            raise ValueError("conversation summary text is required")
        if self.source_hash and len(self.source_hash) != 64:
            raise ValueError("conversation summary source hash is invalid")
        for values in (
            self.facts,
            self.decisions,
            self.commitments,
            self.open_loops,
            self.preferences,
            self.time_anchors,
            self.tool_side_effects,
        ):
            if any(not item.strip() for item in values):
                raise ValueError("conversation summary fields must be non-empty")
        if self.idempotency_key and not self.idempotency_key.strip():
            raise ValueError("conversation summary idempotency key is invalid")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ContextDiagnostics:
    """Bounded diagnostic record for timeline context assembly decisions."""

    kind: str
    detail: str

    def __post_init__(self) -> None:
        if not self.kind.strip() or not self.detail.strip():
            raise ValueError("context diagnostics kind and detail are required")


class ConversationContextRepository(Protocol):
    """Timeline read pinning for unified Agent context assembly."""

    async def create_snapshot(self, user_id: str, scope_id: UUID) -> ConversationSnapshot: ...

    async def list_snapshot_events(
        self,
        user_id: str,
        scope_type: ConversationScopeType,
        scope_id: UUID,
        *,
        max_sequence: int,
        limit: int,
    ) -> tuple[ConversationEventView, ...]: ...

    async def list_summaries(
        self,
        user_id: str,
        scope_type: ConversationScopeType,
        scope_id: UUID,
        *,
        max_sequence: int,
        limit: int = 2,
    ) -> tuple[ConversationSummaryView, ...]: ...


@dataclass(frozen=True, slots=True)
class NotificationEventRequest:
    """Cross-module write request from Notifications to the owner timeline."""

    user_id: str
    event_type: ConversationEventType
    notification_intent_id: UUID
    content: str
    delivery_status: ConversationDeliveryStatus
    occurred_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        if self.event_type not in _TIMELINE_NOTIFICATION_TYPES:
            raise ValueError("notification event type is required")
        if not self.idempotency_key.strip() or len(self.idempotency_key) > _IDEMPOTENCY_LIMIT:
            raise ValueError("notification event idempotency key is required")
        if not self.content.strip() or len(self.content) > _CONTENT_LIMIT:
            raise ValueError("notification event content is required and bounded")
        _require_aware(self.occurred_at, "occurred_at")

    def to_event(self) -> ConversationEvent:
        return ConversationEvent(
            scope_type=ConversationScopeType.OWNER_TIMELINE,
            scope_id=owner_timeline_scope_id(self.user_id),
            user_id=self.user_id,
            event_type=self.event_type,
            occurred_at=self.occurred_at,
            content=self.content,
            idempotency_key=self.idempotency_key,
            notification_intent_id=self.notification_intent_id,
            delivery_status=self.delivery_status,
            content_ref=f"notification-intent:{self.notification_intent_id}",
        )


class NotificationEventCommandPort(Protocol):
    """Narrow Notifications-facing owner timeline append port."""

    async def record_notification_event(self, request: NotificationEventRequest) -> None: ...


def _validate_references(event: ConversationEvent) -> None:
    if event.event_type is ConversationEventType.USER_MESSAGE and event.inbox_item_id is None:
        raise ValueError("user message event requires its inbox item")
    if (
        event.event_type
        in {
            ConversationEventType.AGENT_REPLY,
            ConversationEventType.TOOL_CALL,
            ConversationEventType.TOOL_RESULT,
        }
        and event.run_id is None
    ):
        raise ValueError("run event requires its AgentRun")
    if is_notification_event(event.event_type):
        if event.notification_intent_id is None:
            raise ValueError("notification event requires its notification intent")
        if event.delivery_status is None:
            raise ValueError("notification event requires a delivery status")
    elif event.delivery_status is not None:
        if event.event_type is not ConversationEventType.SYSTEM_RESULT:
            raise ValueError("non-notification events cannot carry a delivery status")
        if event.notification_intent_id is None:
            raise ValueError("system notification event requires its notification intent")


def _validate_scope(event: ConversationEvent) -> None:
    expected = _SCOPE_BY_TYPE[event.event_type]
    if event.scope_type is not expected:
        raise ValueError(
            f"conversation event type {event.event_type.value} requires {expected.value} scope"
        )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"conversation event {field_name} must be timezone-aware")
