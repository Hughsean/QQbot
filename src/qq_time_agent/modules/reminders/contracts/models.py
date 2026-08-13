"""Persistent reminder scheduling and leasing contract."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReminderRef:
    reminder_id: UUID


@dataclass(frozen=True, slots=True)
class ReminderView:
    reminder_id: UUID
    agenda_entry_id: UUID
    agenda_entry_version: int
    due_at: datetime
    status: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class ReminderLease:
    reminder_id: UUID
    agenda_entry_id: UUID
    agenda_entry_version: int
    due_at: datetime
    idempotency_key: str
    lease_owner: str
    attempt_count: int
    max_attempts: int


class ReminderCommandPort(Protocol):
    async def schedule(
        self,
        entry_id: UUID,
        entry_version: int,
        due_at: datetime,
        idempotency_key: str,
    ) -> ReminderRef: ...

    async def cancel_for_entry(self, entry_id: UUID, expected_version: int) -> int: ...

    async def snooze(self, reminder_id: UUID, delay: timedelta, now: datetime) -> ReminderView: ...

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> tuple[ReminderLease, ...]: ...

    async def mark_sent(self, lease: ReminderLease, delivery_ref: str) -> None: ...

    async def mark_failed(
        self, lease: ReminderLease, failure_class: str, next_attempt_at: datetime | None
    ) -> None: ...
