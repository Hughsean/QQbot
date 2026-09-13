from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.notifications.application.ports import StoredDelivery, StoredSuppression
from qq_time_agent.modules.notifications.application.rendering import render_outbound
from qq_time_agent.modules.notifications.application.service import NotificationService
from qq_time_agent.modules.notifications.contracts import NotificationMessage
from qq_time_agent.modules.notifications.domain.models import NotificationKind
from qq_time_agent.modules.reminders.contracts import ReminderLease
from qq_time_agent.modules.task_projection.contracts import (
    ReminderCompletionDecision,
    ReminderCompletionOutcome,
)


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


@dataclass
class InteractiveSender:
    messages: list[NotificationMessage] = field(default_factory=list)

    async def send_message(self, message: NotificationMessage) -> str:
        self.messages.append(message)
        return "interactive-delivery-1"

    async def send_active(self, content: str) -> str:
        raise AssertionError(f"interactive reminder used plain delivery: {content}")


@dataclass
class ActionTokens:
    issued: list[tuple[UUID, UUID, int, int, str, str | None, datetime]] = field(
        default_factory=list
    )

    async def issue(
        self,
        *,
        owner_id: str,
        reminder_id: UUID,
        agenda_entry_id: UUID,
        agenda_entry_version: int,
        occurrence: int,
        action_type: str,
        action_value: str | None,
        expires_at: datetime,
    ) -> str:
        assert owner_id == "owner"
        self.issued.append(
            (
                reminder_id,
                agenda_entry_id,
                agenda_entry_version,
                occurrence,
                action_type,
                action_value,
                expires_at,
            )
        )
        return f"opaque-token-{len(self.issued)}"


@dataclass
class CompletionGate:
    outcome: ReminderCompletionOutcome

    async def evaluate_before_delivery(
        self, user_id: str, agenda_entry_id: UUID, agenda_entry_version: int
    ) -> ReminderCompletionDecision:
        del user_id, agenda_entry_id, agenda_entry_version
        return ReminderCompletionDecision(self.outcome, "verified_completed")


@dataclass
class Suppressions:
    values: dict[str, StoredSuppression] = field(default_factory=dict)

    async def get(self, key: str) -> StoredSuppression | None:
        return self.values.get(key)

    async def record(self, value: StoredSuppression) -> StoredSuppression:
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
    assert sender.contents[0] == (
        "[日程提醒]\n"
        "日程\N{FULLWIDTH COLON}评审\n"
        "时间\N{FULLWIDTH COLON}2026-08-20T15:00+08:00 (北京时间)\n"
        "距离开始还有 30 分钟。"
    )
    assert "回复“完成" not in sender.contents[0]
    assert str(entry.agenda_entry_id) not in sender.contents[0]
    assert str(lease.reminder_id) not in sender.contents[0]


@pytest.mark.asyncio
async def test_reminder_card_uses_opaque_complete_and_defer_buttons() -> None:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    entry = AgendaEntryView(
        uuid4(),
        "TASK_BLOCK",
        "完成测评",
        start,
        start + timedelta(hours=1),
        "Asia/Shanghai",
        "ACTIVE",
        ("inbox:test",),
        uuid4(),
        3,
    )
    lease = ReminderLease(
        uuid4(), entry.agenda_entry_id, 3, start, "key", "worker", 1, 5, occurrence=2
    )
    sender = InteractiveSender()
    tokens = ActionTokens()
    service = NotificationService(sender, Repository(), Clock(), action_tokens=tokens)

    await service.send_reminder("owner", lease, entry)

    message = sender.messages[0]
    assert [(action.action_type, action.label, action.token) for action in message.actions] == [
        ("reminder.complete", "完成", "opaque-token-1"),
        ("reminder.defer", "推迟 15 分钟", "opaque-token-2"),
    ]
    assert str(entry.agenda_entry_id) not in message.content
    assert str(lease.reminder_id) not in message.content
    assert all(value[2:4] == (3, 2) for value in tokens.issued)
    assert all(value[6] == Clock().now() + timedelta(hours=24) for value in tokens.issued)


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
    assert (
        render_outbound(NotificationKind.QQ_DIRECT_AGENT_RESULT, "恢复后的日程清单")
        == "[处理结果]\n恢复后的日程清单"
    )


@pytest.mark.asyncio
async def test_verified_completion_is_persisted_and_never_sent() -> None:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    entry = AgendaEntryView(
        uuid4(),
        "TASK_BLOCK",
        "完成测评",
        start,
        start + timedelta(hours=1),
        "Asia/Shanghai",
        "ACTIVE",
        (),
        uuid4(),
        1,
    )
    lease = ReminderLease(uuid4(), entry.agenda_entry_id, 1, start, "key", "worker", 1, 5)
    sender = Sender()
    suppressions = Suppressions()
    service = NotificationService(
        sender,
        Repository(),
        Clock(),
        completion_gate=CompletionGate(ReminderCompletionOutcome.SUPPRESS_COMPLETED),
        suppressions=suppressions,
    )

    first = await service.send_reminder("owner", lease, entry)
    second = await service.send_reminder("owner", lease, entry)

    assert first == second
    assert first.suppressed and first.delivery_id is None
    assert sender.calls == 0 and len(suppressions.values) == 1
