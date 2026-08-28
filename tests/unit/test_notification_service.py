from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.notifications.application.ports import StoredDelivery
from qq_time_agent.modules.notifications.application.rendering import render_outbound
from qq_time_agent.modules.notifications.application.service import NotificationService
from qq_time_agent.modules.notifications.domain.models import NotificationKind
from qq_time_agent.modules.reminders.contracts import ReminderLease


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
async def test_reminder_delivery_is_idempotent_and_source_labelled() -> None:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    sender = Sender()
    service = NotificationService(sender, Repository(), Clock())
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
    lease = ReminderLease(
        uuid4(), entry.agenda_entry_id, 2, start - timedelta(minutes=30), "key", "worker", 1, 5
    )
    assert await service.send_reminder("owner", lease, entry) == await service.send_reminder(
        "owner", lease, entry
    )
    assert sender.calls == 1
    assert sender.contents[0].startswith("[日程提醒]\n")
    assert "2026-08-20T15:00+08:00" in sender.contents[0]
    assert "距离开始还有 30 分钟。" in sender.contents[0]


@pytest.mark.asyncio
async def test_reminder_version_gate_and_outbound_source_labels() -> None:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    sender = Sender()
    service = NotificationService(sender, Repository(), Clock())
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
    assert sender.calls == 1
    assert "2026-08-20T15:00+08:00" in sender.contents[0]
    assert render_outbound(NotificationKind.DAILY_DIGEST, "[系统通知]") == (
        "[日程摘要]\n\N{FULLWIDTH LEFT SQUARE BRACKET}系统通知\N{FULLWIDTH RIGHT SQUARE BRACKET}"
    )
    assert render_outbound(NotificationKind.AGENDA_CONFLICT, "冲突") == "[日程冲突]\n冲突"
    assert render_outbound(NotificationKind.CONNECTION_REAUTH, "授权失效") == "[系统通知]\n授权失效"
    assert (
        render_outbound(NotificationKind.OUTLOOK_MAIL_RESULT, "主题\N{FULLWIDTH COLON}会议")
        == "[邮件处理\N{FULLWIDTH VERTICAL LINE}Outlook]\n主题\N{FULLWIDTH COLON}会议"
    )
    assert (
        render_outbound(NotificationKind.QQ_MAIL_RESULT, "主题\N{FULLWIDTH COLON}账单")
        == "[邮件处理\N{FULLWIDTH VERTICAL LINE}QQ邮箱]\n主题\N{FULLWIDTH COLON}账单"
    )
