"""Render and idempotently send QQ notifications without changing business state."""

from datetime import datetime

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.actions.contracts import ActionResultView
from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.notifications.application.ports import (
    DeliveryRepository,
    StoredDelivery,
)
from qq_time_agent.modules.notifications.contracts import DeliveryRef, NotificationSender
from qq_time_agent.modules.reminders.contracts import ReminderLease
from qq_time_agent.modules.scheduling.contracts import (
    SchedulingProposalView,
    confirmation_token,
)


class NotificationService:
    def __init__(
        self, sender: NotificationSender, repository: DeliveryRepository, clock: Clock
    ) -> None:
        self._sender = sender
        self._repository = repository
        self._clock = clock

    async def send_confirmation(
        self, user_id: str, proposal: SchedulingProposalView
    ) -> DeliveryRef:
        slot = proposal.recommended_slot
        if slot is None:
            body = f"建议《{proposal.title}》存在冲突, 暂时没有可确认时段。"
        else:
            body = (
                f"建议《{proposal.title}》: {_time(slot.starts_at)} 至 {_time(slot.ends_at)}。"
                f"\n确认码: {confirmation_token(proposal.proposal_id, proposal.version)}"
            )
        return await self._send(
            f"proposal:{proposal.proposal_id}:v{proposal.version}:confirmation", body
        )

    async def send_result(self, user_id: str, result: ActionResultView) -> DeliveryRef:
        body = f"操作已完成: {result.action_type}。\n日程编号: {result.agenda_entry_id or '无'}"
        return await self._send(f"action:{result.action_id}:result:{result.status}", body)

    async def send_reminder(
        self, user_id: str, lease: ReminderLease, entry: AgendaEntryView
    ) -> DeliveryRef:
        if entry.version != lease.agenda_entry_version or entry.status != "ACTIVE":
            raise ValueError("Reminder no longer matches the active Agenda version")
        body = (
            f"提醒:《{entry.title}》将在 {_time(entry.starts_at)} 开始。"
            f"\n回复“完成 {entry.agenda_entry_id}”或“推迟 {lease.reminder_id} 10”。"
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


def _time(value: datetime) -> str:
    return value.isoformat(timespec="minutes")
