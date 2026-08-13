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


class NotificationSender(Protocol):
    async def send_active(self, content: str) -> str: ...


class NotificationPort(Protocol):
    async def send_confirmation(
        self, user_id: str, proposal: SchedulingProposalView
    ) -> DeliveryRef: ...

    async def send_result(self, user_id: str, result: ActionResultView) -> DeliveryRef: ...

    async def send_reminder(
        self, user_id: str, lease: ReminderLease, entry: AgendaEntryView
    ) -> DeliveryRef: ...
