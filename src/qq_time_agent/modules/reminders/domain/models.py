"""Pure persistent Reminder state machine."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4


class ReminderStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    LEASED = "LEASED"
    RETRY_WAIT = "RETRY_WAIT"
    SENT = "SENT"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


@dataclass(slots=True)
class Reminder:
    reminder_id: UUID
    agenda_entry_id: UUID
    agenda_entry_version: int
    due_at: datetime
    idempotency_key: str
    status: ReminderStatus = ReminderStatus.SCHEDULED
    attempt_count: int = 0
    max_attempts: int = 5
    lease_owner: str | None = None
    lease_until: datetime | None = None
    delivery_ref: str | None = None
    failure_class: str | None = None
    occurrence: int = 1

    @classmethod
    def create(
        cls, entry_id: UUID, entry_version: int, due_at: datetime, idempotency_key: str
    ) -> "Reminder":
        if entry_version < 1 or not idempotency_key.strip():
            raise ValueError("Reminder entry version and idempotency key are required")
        _aware(due_at)
        return cls(uuid4(), entry_id, entry_version, due_at, idempotency_key)

    def lease(self, worker_id: str, now: datetime, duration: timedelta) -> None:
        if not worker_id.strip() or duration <= timedelta(0):
            raise ValueError("Reminder lease owner and positive duration are required")
        if self.status not in {ReminderStatus.SCHEDULED, ReminderStatus.RETRY_WAIT}:
            if self.status is not ReminderStatus.LEASED or self.lease_until is None:
                raise ValueError("Reminder is not leaseable")
            if self.lease_until >= now:
                raise ValueError("Reminder lease is still active")
        self.status = ReminderStatus.LEASED
        self.lease_owner = worker_id
        self.lease_until = now + duration
        self.attempt_count += 1

    def mark_sent(self, worker_id: str, delivery_ref: str) -> None:
        self._require_lease(worker_id)
        if not delivery_ref.strip():
            raise ValueError("Reminder delivery reference is required")
        self.status = ReminderStatus.SENT
        self.delivery_ref = delivery_ref
        self._clear_lease()

    def mark_failed(
        self, worker_id: str, failure_class: str, next_attempt_at: datetime | None
    ) -> None:
        self._require_lease(worker_id)
        if not failure_class.strip():
            raise ValueError("Reminder failure class is required")
        if next_attempt_at is not None:
            _aware(next_attempt_at)
        exhausted = self.attempt_count >= self.max_attempts or next_attempt_at is None
        self.status = ReminderStatus.DEAD_LETTER if exhausted else ReminderStatus.RETRY_WAIT
        self.failure_class = failure_class
        if next_attempt_at is not None:
            self.due_at = next_attempt_at
        self._clear_lease()

    def cancel(self) -> None:
        if self.status in {ReminderStatus.SENT, ReminderStatus.DEAD_LETTER}:
            raise ValueError("terminal Reminder cannot be cancelled")
        self.status = ReminderStatus.CANCELLED
        self._clear_lease()

    def snooze(self, delay: timedelta, now: datetime) -> None:
        if self.status is not ReminderStatus.SENT or delay <= timedelta(0):
            raise ValueError("only sent Reminder can be snoozed with a positive delay")
        _aware(now)
        self.status = ReminderStatus.SCHEDULED
        self.due_at = now + delay
        self.delivery_ref = None
        self.failure_class = None
        self.occurrence += 1

    def _require_lease(self, worker_id: str) -> None:
        if self.status is not ReminderStatus.LEASED or self.lease_owner != worker_id:
            raise ValueError("Reminder lease is stale or not owned")

    def _clear_lease(self) -> None:
        self.lease_owner = None
        self.lease_until = None


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reminder time must be timezone-aware")
