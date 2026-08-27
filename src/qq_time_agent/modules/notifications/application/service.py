"""Render and idempotently send QQ notifications without changing business state."""

from datetime import datetime

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.time import local_iso, resolve_timezone
from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.notifications.application.ports import (
    DeliveryRepository,
    StoredDelivery,
)
from qq_time_agent.modules.notifications.application.rendering import render_reminder
from qq_time_agent.modules.notifications.contracts import DeliveryRef, NotificationSender
from qq_time_agent.modules.reminders.contracts import ReminderLease


class NotificationService:
    def __init__(
        self,
        sender: NotificationSender,
        repository: DeliveryRepository,
        clock: Clock,
        owner_timezone: str = "Asia/Shanghai",
    ) -> None:
        self._sender = sender
        self._repository = repository
        self._clock = clock
        resolve_timezone(owner_timezone)
        self._owner_timezone = owner_timezone

    async def send_reminder(
        self, user_id: str, lease: ReminderLease, entry: AgendaEntryView
    ) -> DeliveryRef:
        if entry.version != lease.agenda_entry_version or entry.status != "ACTIVE":
            raise ValueError("Reminder no longer matches the active Agenda version")
        body = render_reminder(
            entry.title,
            _time(entry.starts_at, self._owner_timezone),
            entry.starts_at - lease.due_at,
            entry.agenda_entry_id,
            lease.reminder_id,
        )
        return await self._send(f"reminder:{lease.idempotency_key}:delivery", body)

    async def _send(self, idempotency_key: str, content: str) -> DeliveryRef:
        existing = await self._repository.get(idempotency_key)
        if existing is not None:
            return DeliveryRef(existing.delivery_id)
        delivery_id = await self._sender.send_active(content)
        stored = await self._repository.record(
            StoredDelivery(idempotency_key, delivery_id, self._clock.now())
        )
        return DeliveryRef(stored.delivery_id)


def _time(value: datetime, owner_timezone: str) -> str:
    return local_iso(value, owner_timezone, timespec="minutes")
