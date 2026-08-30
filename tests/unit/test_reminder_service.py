from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from qq_time_agent.modules.reminders.application.service import ReminderService
from qq_time_agent.modules.reminders.domain.models import Reminder


@dataclass
class Repository:
    values: dict[UUID, Reminder] = field(default_factory=dict)

    async def add(self, value: Reminder) -> Reminder:
        existing = next(
            (
                item
                for item in self.values.values()
                if item.idempotency_key == value.idempotency_key
            ),
            None,
        )
        if existing is not None:
            return existing
        self.values[value.reminder_id] = value
        return value

    async def get(self, reminder_id: UUID) -> Reminder | None:
        return self.values.get(reminder_id)

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> tuple[Reminder, ...]:
        due = tuple(value for value in self.values.values() if value.due_at <= now)[:limit]
        for value in due:
            value.lease(worker_id, now, lease_duration)
        return due

    async def save(self, value: Reminder) -> None:
        self.values[value.reminder_id] = value

    async def list_for_entry(self, entry_id: UUID) -> tuple[Reminder, ...]:
        return tuple(value for value in self.values.values() if value.agenda_entry_id == entry_id)


@pytest.mark.asyncio
async def test_reminder_service_schedule_lease_fail_send_snooze_and_cancel() -> None:
    repository = Repository()
    service = ReminderService(repository)
    now = datetime(2026, 8, 20, tzinfo=UTC)
    entry_id = UUID(int=1)
    first = await service.schedule(entry_id, 1, now, "key")
    assert first == await service.schedule(entry_id, 1, now, "key")
    lease = (await service.lease_due(now, "worker", 10, timedelta(minutes=1)))[0]
    await service.mark_failed(lease, "RateLimit", now + timedelta(minutes=1))
    retry = (
        await service.lease_due(now + timedelta(minutes=1), "worker", 10, timedelta(minutes=1))
    )[0]
    await service.mark_sent(retry, "delivery")
    snoozed = await service.snooze(
        first.reminder_id, timedelta(minutes=10), now, expected_occurrence=1
    )
    assert snoozed.status == "SCHEDULED" and snoozed.due_at == now + timedelta(minutes=10)
    retry = (
        await service.lease_due(now + timedelta(minutes=10), "worker", 10, timedelta(minutes=1))
    )[0]
    await service.mark_sent(retry, "delivery-2")
    with pytest.raises(ValueError, match="occurrence is stale"):
        await service.snooze(
            first.reminder_id,
            timedelta(minutes=5),
            now + timedelta(minutes=10),
            expected_occurrence=1,
        )
    current = repository.values[first.reminder_id]
    assert current.occurrence == 2 and current.status.value == "SENT"
    assert await service.cancel_for_entry(entry_id, 1) == 0


@pytest.mark.asyncio
async def test_reminder_service_validates_limit_missing_and_terminal_cancel() -> None:
    service = ReminderService(Repository())
    now = datetime(2026, 8, 20, tzinfo=UTC)
    with pytest.raises(ValueError, match="between"):
        await service.lease_due(now, "worker", 0, timedelta(minutes=1))
    with pytest.raises(LookupError, match="does not exist"):
        await service.snooze(UUID(int=2), timedelta(minutes=1), now, expected_occurrence=1)
