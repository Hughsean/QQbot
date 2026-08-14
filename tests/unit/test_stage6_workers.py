from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.adapters.inbound.workers.proposal_notifications import (
    ProposalNotificationWorker,
)
from qq_time_agent.adapters.inbound.workers.reminders import ReminderWorker
from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.notifications.contracts import DeliveryRef
from qq_time_agent.modules.reminders.contracts import ReminderLease
from qq_time_agent.modules.scheduling.contracts import SchedulingProposalView


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


@dataclass
class Notifications:
    fail_reminder: bool = False
    confirmation_calls: int = 0
    fail_first_confirmation: bool = False

    async def send_reminder(
        self, user_id: str, lease: ReminderLease, entry: AgendaEntryView
    ) -> DeliveryRef:
        if self.fail_reminder:
            raise ConnectionError("QQ unavailable")
        return DeliveryRef("delivery")

    async def send_confirmation(
        self, user_id: str, proposal: SchedulingProposalView
    ) -> DeliveryRef:
        self.confirmation_calls += 1
        if self.fail_first_confirmation and self.confirmation_calls == 1:
            raise ConnectionError("QQ unavailable")
        return DeliveryRef("confirmation")


@dataclass
class Scheduling:
    values: tuple[SchedulingProposalView, ...]

    async def list_pending(self, limit: int) -> tuple[SchedulingProposalView, ...]:
        return self.values[:limit]


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
        reminders,  # type: ignore[arg-type]
        Agenda({entry.agenda_entry_id: entry}),  # type: ignore[arg-type]
        Notifications(),  # type: ignore[arg-type]
        Clock(),
        "worker",
    )
    assert await worker.run_once() == 1
    assert reminders.sent == [good.reminder_id]
    assert reminders.failed[0][1:] == ("StaleAgendaVersion", None)

    failing = Reminders((_lease(entry, 1, 1),))
    await ReminderWorker(
        failing,  # type: ignore[arg-type]
        Agenda({entry.agenda_entry_id: entry}),  # type: ignore[arg-type]
        Notifications(fail_reminder=True),  # type: ignore[arg-type]
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


@pytest.mark.asyncio
async def test_proposal_notifications_isolate_one_delivery_failure() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    proposals = tuple(
        SchedulingProposalView(
            uuid4(),
            1,
            "owner",
            uuid4(),
            "EVENT",
            f"proposal-{index}",
            None,
            (),
            (),
            "conflict",
            (),
            ("source",),
            now,
            "PENDING_CONFIRMATION",
        )
        for index in range(2)
    )
    notifications = Notifications(fail_first_confirmation=True)
    worker = ProposalNotificationWorker(
        Scheduling(proposals),  # type: ignore[arg-type]
        notifications,  # type: ignore[arg-type]
    )
    assert await worker.run_once() == 1
    assert notifications.confirmation_calls == 2
