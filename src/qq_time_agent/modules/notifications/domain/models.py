"""Notification-owned persistent delivery intent state machine."""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class NotificationKind(StrEnum):
    DAILY_DIGEST = "DAILY_DIGEST"
    AGENDA_CONFLICT = "AGENDA_CONFLICT"
    CONNECTION_REAUTH = "CONNECTION_REAUTH"
    AGENT_RESULT = "AGENT_RESULT"


class NotificationIntentState(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    SENT = "SENT"
    AMBIGUOUS = "AMBIGUOUS"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class NotificationIntentDraft:
    user_id: str
    kind: NotificationKind
    subject_key: str
    idempotency_key: str
    template_version: str
    content: str
    available_at: datetime

    def __post_init__(self) -> None:
        values = (self.user_id, self.subject_key, self.idempotency_key, self.template_version)
        if any(not value.strip() for value in values):
            raise ValueError("notification intent identifiers are required")
        if len(self.subject_key) > 240 or len(self.idempotency_key) > 240:
            raise ValueError("notification intent key is too long")
        if not self.content.strip() or len(self.content) > 4000:
            raise ValueError("notification content must be non-empty and bounded")
        _aware(self.available_at)


@dataclass(slots=True)
class NotificationIntent:
    intent_id: UUID
    draft: NotificationIntentDraft
    state: NotificationIntentState
    created_at: datetime
    updated_at: datetime
    attempt_count: int = 0
    lease_owner: str | None = None
    lease_until: datetime | None = None
    provider_delivery_id: str | None = None
    failure_class: str | None = None
    sent_at: datetime | None = None
    version: int = 1

    @classmethod
    def create(cls, draft: NotificationIntentDraft, now: datetime) -> "NotificationIntent":
        _aware(now)
        return cls(uuid4(), draft, NotificationIntentState.PENDING, now, now)

    def lease(self, owner: str, until: datetime, now: datetime) -> None:
        if self.state is not NotificationIntentState.PENDING or not owner.strip():
            raise ValueError("notification intent is not leaseable")
        if until <= now:
            raise ValueError("notification lease must end in the future")
        self.state = NotificationIntentState.LEASED
        self.lease_owner = owner
        self.lease_until = until
        self.attempt_count += 1
        self.updated_at = now
        self.version += 1

    def defer(self, available_at: datetime, now: datetime) -> None:
        self._require_leased()
        if available_at <= now:
            raise ValueError("deferred notification time must be in the future")
        self.state = NotificationIntentState.PENDING
        self.draft = replace(self.draft, available_at=available_at)
        self._finish(now)

    def mark_pre_send_failure(
        self,
        failure_class: str,
        now: datetime,
        retry_at: datetime | None,
        max_attempts: int,
    ) -> None:
        self._require_leased()
        if not failure_class.strip() or max_attempts < 1:
            raise ValueError("notification failure policy is invalid")
        self.failure_class = failure_class
        if retry_at is not None and self.attempt_count < max_attempts:
            if retry_at <= now:
                raise ValueError("notification retry must be in the future")
            self.state = NotificationIntentState.PENDING
            self.draft = replace(self.draft, available_at=retry_at)
        else:
            self.state = NotificationIntentState.DEAD_LETTER
        self._finish(now)

    def mark_sent(self, delivery_id: str, now: datetime) -> None:
        self._require_leased()
        if not delivery_id.strip():
            raise ValueError("provider delivery id is required")
        self.state = NotificationIntentState.SENT
        self.provider_delivery_id = delivery_id
        self.sent_at = now
        self._finish(now)

    def mark_ambiguous(self, failure_class: str, now: datetime) -> None:
        self._require_leased()
        self.state = NotificationIntentState.AMBIGUOUS
        self.failure_class = failure_class
        self._finish(now)

    def cancel(self, now: datetime) -> None:
        if self.state in {NotificationIntentState.SENT, NotificationIntentState.AMBIGUOUS}:
            raise ValueError("terminal notification intent cannot be cancelled")
        self.state = NotificationIntentState.CANCELLED
        self._finish(now)

    def _require_leased(self) -> None:
        if self.state is not NotificationIntentState.LEASED:
            raise ValueError("notification intent is not leased")

    def _finish(self, now: datetime) -> None:
        self.lease_owner = None
        self.lease_until = None
        self.updated_at = now
        self.version += 1


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware notification time required")
