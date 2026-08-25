"""Provider-neutral notification delivery contracts."""

from dataclasses import dataclass
from typing import Protocol

from qq_time_agent.modules.actions.contracts import ActionResultView
from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.reminders.contracts import ReminderLease
from qq_time_agent.modules.scheduling.contracts import SchedulingProposalView


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
    async def send_clarification(
        self, user_id: str, subject_key: str, content: str
    ) -> DeliveryRef: ...

    async def send_confirmation(
        self, user_id: str, proposal: SchedulingProposalView
    ) -> DeliveryRef: ...

    async def send_result(self, user_id: str, result: ActionResultView) -> DeliveryRef: ...

    async def send_reminder(
        self, user_id: str, lease: ReminderLease, entry: AgendaEntryView
    ) -> DeliveryRef: ...
