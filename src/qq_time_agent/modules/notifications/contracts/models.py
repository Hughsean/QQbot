"""Provider-neutral notification delivery contracts."""

from dataclasses import dataclass
from typing import Protocol

from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.reminders.contracts import ReminderLease


@dataclass(frozen=True, slots=True)
class DeliveryRef:
    delivery_id: str


class NotificationPreSendTransientError(RuntimeError):
    """The provider request definitely was not sent and may be retried."""


class NotificationPreSendPermanentError(RuntimeError):
    """The provider request definitely was not sent and must be dead-lettered."""


class NotificationSender(Protocol):
    async def send_active(self, content: str) -> str: ...


@dataclass(frozen=True, slots=True)
class NotificationIntentMetrics:
    pending: float
    leased: float
    ambiguous: float
    dead_letter: float


class NotificationMetricsPort(Protocol):
    async def notification_metrics(self) -> NotificationIntentMetrics: ...


class NotificationPort(Protocol):
    async def send_reminder(
        self, user_id: str, lease: ReminderLease, entry: AgendaEntryView
    ) -> DeliveryRef: ...
