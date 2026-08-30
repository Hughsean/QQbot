from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from qq_time_agent.modules.notifications.application.reminder_actions import (
    DeferReminderHandler,
    ReminderInteractionDispatcher,
)
from qq_time_agent.modules.notifications.contracts import (
    ReminderActionResult,
    ReminderActionToken,
)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 20, tzinfo=UTC)


def token(action_type: str = "reminder.defer", value: str | None = "15m") -> ReminderActionToken:
    return ReminderActionToken(
        "hash", "owner", UUID(int=1), UUID(int=2), 1, 1, action_type, value,
        datetime(2026, 8, 21, tzinfo=UTC),
    )


class Reminders:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[UUID, timedelta, datetime, int]] = []
        self.error = error

    async def snooze(
        self,
        reminder_id: UUID,
        delay: timedelta,
        now: datetime,
        *,
        expected_occurrence: int,
    ) -> object:
        if self.error is not None:
            raise self.error
        self.calls.append((reminder_id, delay, now, expected_occurrence))
        return object()


class Tokens:
    def __init__(self, action: ReminderActionToken | None) -> None:
        self.action = action
        self.calls: list[tuple[str, str, datetime]] = []

    async def consume(self, token: str, owner_id: str, now: datetime) -> ReminderActionToken | None:
        self.calls.append((token, owner_id, now))
        return self.action


@pytest.mark.asyncio
async def test_defer_handler_passes_controlled_delay_and_occurrence() -> None:
    reminders = Reminders()
    handler = DeferReminderHandler(reminders, Clock())

    result = await handler.handle(token())

    assert result == ReminderActionResult("已推迟 15m。")
    assert reminders.calls == [(UUID(int=1), timedelta(minutes=15), Clock().now(), 1)]


@pytest.mark.asyncio
async def test_defer_handler_rejects_unknown_delay() -> None:
    reminders = Reminders()
    handler = DeferReminderHandler(reminders, Clock())

    with pytest.raises(ValueError, match="不受支持"):
        await handler.handle(token(value="2h"))
    assert reminders.calls == []


@pytest.mark.asyncio
async def test_dispatcher_does_not_consume_unknown_action() -> None:
    tokens = Tokens(token("reminder.unknown"))
    dispatcher = ReminderInteractionDispatcher(tokens, {}, Clock())

    result = await dispatcher.dispatch("interaction", "owner", "reminder.unknown", "raw")

    assert result.idempotent is True
    assert tokens.calls == []


@pytest.mark.asyncio
async def test_dispatcher_rejects_action_type_mismatch() -> None:
    tokens = Tokens(token("reminder.complete"))
    reminders = Reminders()
    dispatcher = ReminderInteractionDispatcher(
        tokens,
        {"reminder.defer": DeferReminderHandler(reminders, Clock())},
        Clock(),
    )

    result = await dispatcher.dispatch("interaction", "owner", "reminder.defer", "raw")

    assert result == ReminderActionResult("此按钮已过期或已处理。", idempotent=True)
    assert reminders.calls == []


@pytest.mark.asyncio
async def test_dispatcher_maps_handler_state_error_to_idempotent_result() -> None:
    reminders = Reminders(ValueError("stale"))
    dispatcher = ReminderInteractionDispatcher(
        Tokens(token()),
        {"reminder.defer": DeferReminderHandler(reminders, Clock())},
        Clock(),
    )

    result = await dispatcher.dispatch("interaction", "owner", "reminder.defer", "raw")

    assert result == ReminderActionResult("当前提醒状态已变化, 请使用最新提醒。", idempotent=True)
