"""Independent durable Reminder worker; model availability is irrelevant."""

import logging
from datetime import timedelta

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agenda.contracts import AgendaQueryPort
from qq_time_agent.modules.notifications.contracts import NotificationPort
from qq_time_agent.modules.reminders.contracts import ReminderCommandPort

LOGGER = logging.getLogger(__name__)


class ReminderWorker:
    def __init__(
        self,
        reminders: ReminderCommandPort,
        agenda: AgendaQueryPort,
        notifications: NotificationPort,
        clock: Clock,
        worker_id: str,
    ) -> None:
        self._reminders = reminders
        self._agenda = agenda
        self._notifications = notifications
        self._clock = clock
        self._worker_id = worker_id

    async def run_once(self) -> int:
        now = self._clock.now()
        leases = await self._reminders.lease_due(now, self._worker_id, 20, timedelta(minutes=2))
        sent = 0
        for lease in leases:
            entry = await self._agenda.get_entry(lease.agenda_entry_id)
            if (
                entry is None
                or entry.version != lease.agenda_entry_version
                or entry.status != "ACTIVE"
            ):
                await self._reminders.mark_failed(lease, "StaleAgendaVersion", None)
                LOGGER.warning(
                    "reminder rejected because agenda version is stale",
                    extra={
                        "reminder_id": lease.reminder_id,
                        "attempt": lease.attempt_count,
                        "failure_class": "StaleAgendaVersion",
                    },
                )
                continue
            try:
                delivery = await self._notifications.send_reminder("owner", lease, entry)
            except Exception as exc:
                retry = None
                if lease.attempt_count < lease.max_attempts:
                    retry = now + timedelta(seconds=min(300, 2**lease.attempt_count * 5))
                failure_class = type(exc).__name__
                await self._reminders.mark_failed(lease, failure_class, retry)
                LOGGER.warning(
                    "reminder delivery failed",
                    extra={
                        "reminder_id": lease.reminder_id,
                        "attempt": lease.attempt_count,
                        "failure_class": failure_class,
                    },
                )
            else:
                await self._reminders.mark_sent(lease, delivery.delivery_id)
                sent += 1
        return sent
