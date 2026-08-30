"""Reminder button callbacks and controlled business actions."""

from datetime import timedelta
from typing import ClassVar

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agenda.contracts import AgendaCommandPort, AgendaQueryPort
from qq_time_agent.modules.notifications.contracts import (
    InteractionDispatcher,
    ReminderActionHandler,
    ReminderActionResult,
    ReminderActionToken,
    ReminderActionTokenPort,
)
from qq_time_agent.modules.reminders.contracts import ReminderCommandPort


class ReminderInteractionDispatcher(InteractionDispatcher):
    def __init__(
        self,
        tokens: ReminderActionTokenPort,
        handlers: dict[str, ReminderActionHandler],
        clock: Clock,
    ) -> None:
        self._tokens = tokens
        self._handlers = handlers
        self._clock = clock

    async def dispatch(
        self, _interaction_id: str, owner_id: str, button_id: str, button_data: str
    ) -> ReminderActionResult:
        handler = self._handlers.get(button_id)
        if handler is None:
            return ReminderActionResult("此按钮操作不受支持。", idempotent=True)
        action = await self._tokens.consume(button_data, owner_id, self._clock.now())
        if action is None or action.action_type != button_id:
            return ReminderActionResult("此按钮已过期或已处理。", idempotent=True)
        try:
            return await handler.handle(action)
        except (LookupError, PermissionError, ValueError):
            return ReminderActionResult("当前提醒状态已变化, 请使用最新提醒。", idempotent=True)


class CompleteReminderHandler(ReminderActionHandler):
    def __init__(
        self,
        agenda: AgendaCommandPort,
        agenda_query: AgendaQueryPort,
        reminders: ReminderCommandPort,
    ) -> None:
        self._agenda = agenda
        self._agenda_query = agenda_query
        self._reminders = reminders

    async def handle(self, action: ReminderActionToken) -> ReminderActionResult:
        entry = await self._agenda_query.get_entry(action.agenda_entry_id)
        if entry is None or entry.version != action.agenda_entry_version:
            raise ValueError("日程版本已变化, 请使用最新提醒")
        if entry.status != "ACTIVE":
            return ReminderActionResult("该日程已经完成或取消。", idempotent=True)
        await self._agenda.complete_entry(
            action.agenda_entry_id,
            action.agenda_entry_version,
            f"qq:reminder:{action.reminder_id}:occurrence:{action.occurrence}:complete",
        )
        await self._reminders.cancel_for_entry(
            action.agenda_entry_id, action.agenda_entry_version
        )
        return ReminderActionResult("日程已完成。")


class DeferReminderHandler(ReminderActionHandler):
    _DELAYS: ClassVar[dict[str, timedelta]] = {
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
    }

    def __init__(self, reminders: ReminderCommandPort, clock: Clock) -> None:
        self._reminders = reminders
        self._clock = clock

    async def handle(self, action: ReminderActionToken) -> ReminderActionResult:
        delay = self._DELAYS.get(action.action_value or "")
        if delay is None:
            raise ValueError("推迟时长不受支持")
        await self._reminders.snooze(
            action.reminder_id,
            delay,
            self._clock.now(),
            expected_occurrence=action.occurrence,
        )
        return ReminderActionResult(f"已推迟 {action.action_value}。")
