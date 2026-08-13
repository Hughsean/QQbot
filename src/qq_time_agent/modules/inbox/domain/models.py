"""Pure Inbox state machine and immutable mail envelope."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from qq_time_agent.contracts.source import IngressType, SourceType, TrustLevel


class InboxStatus(StrEnum):
    RECEIVED = "RECEIVED"
    NORMALIZED = "NORMALIZED"
    UNDERSTOOD = "UNDERSTOOD"
    PROPOSED = "PROPOSED"
    COMPLETED = "COMPLETED"
    IGNORED = "IGNORED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


@dataclass(frozen=True, slots=True)
class MailEnvelope:
    connection_id: UUID
    user_id: str
    external_id: str
    thread_id: str | None
    sender_id: str
    sender_display: str | None
    occurred_at: datetime
    received_at: datetime
    content_hash: str
    source_type: SourceType = SourceType.MICROSOFT_MAIL
    ingress_type: IngressType = IngressType.SYNC
    trust_level: TrustLevel = TrustLevel.T2
    dedupe_key: str | None = None

    def __post_init__(self) -> None:
        required = (self.user_id, self.external_id, self.sender_id, self.content_hash)
        if any(not value.strip() for value in required):
            raise ValueError("mail envelope identifiers and content hash are required")
        _require_aware(self.occurred_at)
        _require_aware(self.received_at)


@dataclass(slots=True)
class InboxItem:
    inbox_item_id: UUID
    envelope: MailEnvelope
    raw_content_ref: UUID
    status: InboxStatus = InboxStatus.RECEIVED
    failure_class: str | None = None
    retry_count: int = 0
    version: int = 1

    @classmethod
    def receive(cls, envelope: MailEnvelope, raw_content_ref: UUID) -> "InboxItem":
        return cls(uuid4(), envelope, raw_content_ref)

    def mark_normalized(self) -> None:
        self._transition(
            {InboxStatus.RECEIVED, InboxStatus.FAILED_RETRYABLE}, InboxStatus.NORMALIZED
        )

    def mark_completed(self) -> None:
        self._transition(
            {InboxStatus.NORMALIZED, InboxStatus.UNDERSTOOD, InboxStatus.PROPOSED},
            InboxStatus.COMPLETED,
        )

    def mark_understood(self) -> None:
        self._transition({InboxStatus.NORMALIZED}, InboxStatus.UNDERSTOOD)

    def mark_proposed(self) -> None:
        self._transition({InboxStatus.UNDERSTOOD}, InboxStatus.PROPOSED)

    def mark_needs_review(self) -> None:
        self._transition({InboxStatus.NORMALIZED}, InboxStatus.NEEDS_REVIEW)

    def mark_ignored(self) -> None:
        self._transition({InboxStatus.NORMALIZED}, InboxStatus.IGNORED)

    def mark_failed(self, failure_class: str, retryable: bool) -> None:
        if not failure_class.strip():
            raise ValueError("failure_class is required")
        if self.status in {InboxStatus.COMPLETED, InboxStatus.IGNORED, InboxStatus.FAILED_FINAL}:
            raise ValueError("terminal Inbox item cannot fail")
        self.status = InboxStatus.FAILED_RETRYABLE if retryable else InboxStatus.FAILED_FINAL
        self.failure_class = failure_class
        self.retry_count += 1
        self.version += 1

    def retry(self) -> None:
        self._transition({InboxStatus.FAILED_RETRYABLE}, InboxStatus.RECEIVED)

    def _transition(self, allowed: set[InboxStatus], target: InboxStatus) -> None:
        if self.status not in allowed:
            raise ValueError(f"invalid Inbox transition from {self.status.value} to {target.value}")
        self.status = target
        self.failure_class = None
        self.version += 1

    @property
    def source_type(self) -> SourceType:
        return self.envelope.source_type

    @property
    def ingress_type(self) -> IngressType:
        return self.envelope.ingress_type

    @property
    def trust_level(self) -> TrustLevel:
        return self.envelope.trust_level


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
