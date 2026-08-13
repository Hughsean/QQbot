"""Reminder scheduling, durable leasing, retry and snooze use cases."""

from datetime import datetime, timedelta
from uuid import UUID

from qq_time_agent.modules.reminders.application.ports import ReminderRepository
from qq_time_agent.modules.reminders.contracts import ReminderLease, ReminderRef, ReminderView
from qq_time_agent.modules.reminders.domain.models import Reminder, ReminderStatus


class ReminderService:
    def __init__(self, repository: ReminderRepository) -> None:
        self._repository = repository

    async def schedule(
        self,
        entry_id: UUID,
        entry_version: int,
        due_at: datetime,
        idempotency_key: str,
    ) -> ReminderRef:
        value = await self._repository.add(
            Reminder.create(entry_id, entry_version, due_at, idempotency_key)
        )
        return ReminderRef(value.reminder_id)

    async def cancel_for_entry(self, entry_id: UUID, expected_version: int) -> int:
        values = await self._repository.list_for_entry(entry_id)
        count = 0
        for value in values:
            if value.agenda_entry_version <= expected_version and value.status not in {
                ReminderStatus.SENT,
                ReminderStatus.DEAD_LETTER,
                ReminderStatus.CANCELLED,
            }:
                value.cancel()
                await self._repository.save(value)
                count += 1
        return count

    async def snooze(self, reminder_id: UUID, delay: timedelta, now: datetime) -> ReminderView:
        value = await self._require(reminder_id)
        value.snooze(delay, now)
        await self._repository.save(value)
        return _view(value)

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> tuple[ReminderLease, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("Reminder lease limit must be between 1 and 100")
        values = await self._repository.lease_due(now, worker_id, limit, lease_duration)
        return tuple(_lease(value) for value in values)

    async def mark_sent(self, lease: ReminderLease, delivery_ref: str) -> None:
        value = await self._require(lease.reminder_id)
        value.mark_sent(lease.lease_owner, delivery_ref)
        await self._repository.save(value)

    async def mark_failed(
        self, lease: ReminderLease, failure_class: str, next_attempt_at: datetime | None
    ) -> None:
        value = await self._require(lease.reminder_id)
        value.mark_failed(lease.lease_owner, failure_class, next_attempt_at)
        await self._repository.save(value)

    async def _require(self, reminder_id: UUID) -> Reminder:
        value = await self._repository.get(reminder_id)
        if value is None:
            raise LookupError("Reminder does not exist")
        return value


def _lease(value: Reminder) -> ReminderLease:
    if value.lease_owner is None:
        raise RuntimeError("leased Reminder omitted owner")
    return ReminderLease(
        value.reminder_id,
        value.agenda_entry_id,
        value.agenda_entry_version,
        value.due_at,
        f"{value.idempotency_key}:occurrence:{value.occurrence}",
        value.lease_owner,
        value.attempt_count,
        value.max_attempts,
    )


def _view(value: Reminder) -> ReminderView:
    return ReminderView(
        value.reminder_id,
        value.agenda_entry_id,
        value.agenda_entry_version,
        value.due_at,
        value.status.value,
        value.attempt_count,
    )
