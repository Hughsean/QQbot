from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.reminders import ReminderWorker
from qq_time_agent.modules.agenda.contracts import AgendaEntryView, BusyInterval
from qq_time_agent.modules.notifications.contracts import DeliveryRef
from qq_time_agent.modules.reminders.contracts import ReminderLease, ReminderRef, ReminderView


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 20, tzinfo=UTC)


@dataclass
class Reminders:
    leases: tuple[ReminderLease, ...]
    sent: list[UUID] = field(default_factory=list)
    failed: list[tuple[UUID, str, datetime | None]] = field(default_factory=list)

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: object
    ) -> tuple[ReminderLease, ...]:
        return self.leases

    async def schedule(
        self, entry_id: UUID, entry_version: int, due_at: datetime, idempotency_key: str
    ) -> ReminderRef:
        del entry_id, entry_version, due_at, idempotency_key
        return ReminderRef(uuid4())

    async def cancel_for_entry(self, entry_id: UUID, expected_version: int) -> int:
        del entry_id, expected_version
        return 0

    async def snooze(
        self,
        reminder_id: UUID,
        delay: timedelta,
        now: datetime,
        *,
        expected_occurrence: int,
    ) -> ReminderView:
        del reminder_id, delay, now, expected_occurrence
        raise NotImplementedError

    async def reschedule(self, reminder_id: UUID, due_at: datetime, now: datetime) -> ReminderView:
        del reminder_id, due_at, now
        raise NotImplementedError

    async def list_for_entry(self, entry_id: UUID) -> tuple[ReminderView, ...]:
        del entry_id
        return ()

    async def mark_sent(self, lease: ReminderLease, delivery_ref: str) -> None:
        self.sent.append(lease.reminder_id)

    async def mark_failed(
        self, lease: ReminderLease, failure_class: str, next_attempt_at: datetime | None
    ) -> None:
        self.failed.append((lease.reminder_id, failure_class, next_attempt_at))


@dataclass
class Agenda:
    values: dict[UUID, AgendaEntryView]

    async def get_entry(self, entry_id: UUID) -> AgendaEntryView | None:
        return self.values.get(entry_id)

    async def get_busy_intervals(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[BusyInterval, ...]:
        del range_start, range_end
        return ()

    async def find_active_by_title(self, title: str) -> tuple[AgendaEntryView, ...]:
        return tuple(value for value in self.values.values() if value.title == title)


@dataclass
class Notifications:
    fail_reminder: bool = False

    async def send_reminder(
        self, user_id: str, lease: ReminderLease, entry: AgendaEntryView
    ) -> DeliveryRef:
        if self.fail_reminder:
            raise ConnectionError("QQ unavailable")
        return DeliveryRef("delivery")


def _entry(version: int = 1) -> AgendaEntryView:
    start = datetime(2026, 8, 20, 1, tzinfo=UTC)
    return AgendaEntryView(
        uuid4(),
        "EVENT",
        "评审",
        start,
        datetime(2026, 8, 20, 2, tzinfo=UTC),
        "UTC",
        "ACTIVE",
        ("source",),
        uuid4(),
        version,
    )


def _lease(entry: AgendaEntryView, version: int, attempts: int = 1) -> ReminderLease:
    return ReminderLease(
        uuid4(), entry.agenda_entry_id, version, entry.starts_at, "key", "worker", attempts, 5
    )


@pytest.mark.asyncio
async def test_reminder_worker_sends_stale_dead_letters_and_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = _entry()
    good = _lease(entry, 1)
    stale = _lease(entry, 2)
    reminders = Reminders((good, stale))
    worker = ReminderWorker(
        reminders,
        Agenda({entry.agenda_entry_id: entry}),
        Notifications(),
        Clock(),
        "worker",
    )
    assert await worker.run_once() == 1
    assert reminders.sent == [good.reminder_id]
    assert reminders.failed[0][1:] == ("StaleAgendaVersion", None)

    failing = Reminders((_lease(entry, 1, 1),))
    await ReminderWorker(
        failing,
        Agenda({entry.agenda_entry_id: entry}),
        Notifications(fail_reminder=True),
        Clock(),
        "worker",
    ).run_once()
    assert failing.failed[0][1] == "ConnectionError"
    assert failing.failed[0][2] is not None
    failure_classes = {getattr(record, "failure_class", None) for record in caplog.records}
    assert {"StaleAgendaVersion", "ConnectionError"} <= failure_classes
    assert any(
        getattr(record, "reminder_id", None) == stale.reminder_id for record in caplog.records
    )
    assert "评审" not in caplog.text
