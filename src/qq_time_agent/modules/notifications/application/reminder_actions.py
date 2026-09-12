"""Reminder button callbacks and controlled business actions."""

from datetime import timedelta
from typing import ClassVar

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.actions.contracts import CalendarActionPort
from qq_time_agent.modules.agenda.contracts import AgendaQueryPort
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
        action = await self._tokens.claim(
            button_data, owner_id, button_id, self._clock.now()
        )
        if action is None:
            return ReminderActionResult("此按钮已过期或已处理。", idempotent=True)
        try:
            result = await handler.handle(action)
        except (LookupError, PermissionError, ValueError):
            await self._tokens.resolve(action.token_hash, self._clock.now(), "REJECTED")
            return ReminderActionResult("当前提醒状态已变化, 请使用最新提醒。", idempotent=True)
        except Exception:
            await self._tokens.resolve(action.token_hash, self._clock.now(), "FAILED")
            raise
        await self._tokens.resolve(action.token_hash, self._clock.now(), "SUCCEEDED")
        return result


class CompleteReminderHandler(ReminderActionHandler):
    def __init__(self, actions: CalendarActionPort, action_user_id: str) -> None:
        if not action_user_id.strip():
            raise ValueError("Action user is required")
        self._actions = actions
        self._action_user_id = action_user_id

    async def handle(self, action: ReminderActionToken) -> ReminderActionResult:
        await self._actions.execute_calendar_operation(
            self._action_user_id,
            "COMPLETE_AGENDA",
            {
                "agenda_entry_id": str(action.agenda_entry_id),
                "expected_version": action.agenda_entry_version,
            },
            (
                f"qq:reminder:{action.reminder_id}:"
                f"occurrence:{action.occurrence}:complete"
            ),
        )
        return ReminderActionResult("日程已完成。")


class DeferReminderHandler(ReminderActionHandler):
    _DELAYS: ClassVar[dict[str, timedelta]] = {
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
    }

    def __init__(
        self,
        reminders: ReminderCommandPort,
        agenda_query: AgendaQueryPort,
        clock: Clock,
    ) -> None:
        self._reminders = reminders
        self._agenda_query = agenda_query
        self._clock = clock

    async def handle(self, action: ReminderActionToken) -> ReminderActionResult:
        entry = await self._agenda_query.get_entry(action.agenda_entry_id)
        if (
            entry is None
            or entry.version != action.agenda_entry_version
            or entry.status != "ACTIVE"
        ):
            raise ValueError("日程状态已变化, 请使用最新提醒")
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
