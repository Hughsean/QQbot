"""Independent durable Reminder worker; model availability is irrelevant."""

import logging
from datetime import datetime, timedelta

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agenda.contracts import AgendaQueryPort
from qq_time_agent.modules.notifications.contracts import NotificationPort
from qq_time_agent.modules.reminders.contracts import ReminderCommandPort, ReminderLease

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
        return sum([await self._process(lease, now) for lease in leases])

    async def _process(self, lease: ReminderLease, now: datetime) -> int:
        entry = await self._agenda.get_entry(lease.agenda_entry_id)
        if (
            entry is None
            or entry.version != lease.agenda_entry_version
            or entry.status != "ACTIVE"
        ):
            await self._fail(lease, "StaleAgendaVersion", None)
            return 0
        try:
            delivery = await self._notifications.send_reminder("owner", lease, entry)
        except Exception as exc:
            retry = (
                now + timedelta(seconds=min(300, 2**lease.attempt_count * 5))
                if lease.attempt_count < lease.max_attempts
                else None
            )
            await self._fail(lease, type(exc).__name__, retry)
            return 0
        if delivery.suppressed:
            return 0
        if delivery.delivery_id is None:
            await self._fail(lease, "MissingDeliveryReference", None)
            return 0
        try:
            await self._reminders.mark_sent(lease, delivery.delivery_id)
        except ValueError:
            LOGGER.info(
                "reminder delivery settled after lease cancellation",
                extra={"reminder_id": lease.reminder_id},
            )
        return 1

    async def _fail(
        self, lease: ReminderLease, failure_class: str, retry: datetime | None
    ) -> None:
        try:
            await self._reminders.mark_failed(lease, failure_class, retry)
        except ValueError:
            LOGGER.info(
                "reminder failure ignored after lease cancellation",
                extra={"reminder_id": lease.reminder_id},
            )
            return
        LOGGER.warning(
            "reminder delivery failed",
            extra={
                "reminder_id": lease.reminder_id,
                "attempt": lease.attempt_count,
                "failure_class": failure_class,
            },
        )
