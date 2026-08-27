from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.actions.contracts import ActionResultView
from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.notifications.application.ports import StoredDelivery
from qq_time_agent.modules.notifications.application.service import NotificationService
from qq_time_agent.modules.reminders.contracts import ReminderLease
from qq_time_agent.modules.scheduling.contracts import ProposalSlot, SchedulingProposalView


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 20, tzinfo=UTC)


@dataclass
class Sender:
    calls: int = 0
    contents: list[str] = field(default_factory=list)

    async def send_active(self, content: str) -> str:
        self.calls += 1
        self.contents.append(content)
        return "delivery-1"


@dataclass
class Repository:
    values: dict[str, StoredDelivery] = field(default_factory=dict)

    async def get(self, key: str) -> StoredDelivery | None:
        return self.values.get(key)

    async def record(self, value: StoredDelivery) -> StoredDelivery:
        return self.values.setdefault(value.idempotency_key, value)


@pytest.mark.asyncio
async def test_confirmation_delivery_is_idempotent() -> None:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    proposal = SchedulingProposalView(
        uuid4(),
        1,
        "owner",
        uuid4(),
        "EVENT",
        "评审",
        ProposalSlot(start, start + timedelta(hours=1), "Asia/Shanghai"),
        (),
        (),
        "固定时间",
        (),
        ("inbox:test",),
        start + timedelta(days=1),
        "PENDING_CONFIRMATION",
    )
    sender = Sender()
    service = NotificationService(sender, Repository(), Clock())
    assert await service.send_confirmation("owner", proposal) == await service.send_confirmation(
        "owner", proposal
    )
    assert sender.calls == 1
    assert "2026-08-20T15:00+08:00" in sender.contents[0]


@pytest.mark.asyncio
async def test_conflict_result_and_reminder_rendering_with_version_gate() -> None:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    sender = Sender()
    service = NotificationService(sender, Repository(), Clock())
    conflict = SchedulingProposalView(
        uuid4(),
        1,
        "owner",
        uuid4(),
        "EVENT",
        "冲突会议",
        None,
        (),
        (),
        "冲突",
        (),
        ("inbox:test",),
        start + timedelta(days=1),
        "PENDING_CONFIRMATION",
    )
    await service.send_confirmation("owner", conflict)
    action = ActionResultView(uuid4(), "CREATE_AGENDA", "SUCCEEDED", uuid4(), 1, uuid4())
    await service.send_result("owner", action)
    entry = AgendaEntryView(
        uuid4(),
        "EVENT",
        "评审",
        start,
        start + timedelta(hours=1),
        "Asia/Shanghai",
        "ACTIVE",
        ("inbox:test",),
        uuid4(),
        2,
    )
    lease = ReminderLease(uuid4(), entry.agenda_entry_id, 2, start, "key", "worker", 1, 5)
    await service.send_reminder("owner", lease, entry)
    with pytest.raises(ValueError, match="no longer matches"):
        await service.send_reminder(
            "owner",
            ReminderLease(
                lease.reminder_id,
                lease.agenda_entry_id,
                1,
                lease.due_at,
                lease.idempotency_key,
                lease.lease_owner,
                lease.attempt_count,
                lease.max_attempts,
            ),
            entry,
        )
    assert sender.calls == 3
    assert "2026-08-20T15:00+08:00" in sender.contents[2]
