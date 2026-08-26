"""Only confirmed Actions may write Agenda and schedule Reminders."""

from collections.abc import Mapping
from datetime import timedelta
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.actions.application.calendar import CalendarActionExecutor
from qq_time_agent.modules.actions.application.ports import ActionRepository
from qq_time_agent.modules.actions.contracts import ActionResultView, UndoRequestView
from qq_time_agent.modules.actions.domain.models import ActionRequest, ActionStatus
from qq_time_agent.modules.agenda.contracts import AgendaCommandPort, AgendaDraft, AgendaQueryPort
from qq_time_agent.modules.audit.contracts import AuditEvent, AuditPort
from qq_time_agent.modules.reminders.contracts import ReminderCommandPort
from qq_time_agent.modules.scheduling.contracts import SchedulingProposalView


class ActionService:
    def __init__(
        self,
        repository: ActionRepository,
        agenda: AgendaCommandPort,
        reminders: ReminderCommandPort,
        clock: Clock,
        audit: AuditPort | None = None,
        agenda_query: AgendaQueryPort | None = None,
    ) -> None:
        self._repository = repository
        self._agenda = agenda
        self._reminders = reminders
        self._clock = clock
        self._audit = audit
        self._agenda_query = agenda_query
        self._calendar = (
            CalendarActionExecutor(repository, agenda, agenda_query, reminders, clock, audit)
            if agenda_query is not None
            else None
        )

    async def execute_calendar_operation(
        self,
        user_id: str,
        operation: str,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> ActionResultView:
        if self._calendar is None:
            raise RuntimeError("Agenda query port is required for calendar operations")
        return await self._calendar.execute(user_id, operation, payload, idempotency_key)

    async def execute_confirmed(
        self, proposal: SchedulingProposalView, reminder_lead_minutes: int
    ) -> ActionResultView:
        if proposal.status != "CONFIRMED" or proposal.recommended_slot is None:
            raise PermissionError("current confirmed Proposal with a slot is required")
        if reminder_lead_minutes < 0:
            raise ValueError("Reminder lead must be non-negative")
        action = await self._repository.add(
            ActionRequest.create_agenda(
                proposal.user_id, proposal.proposal_id, proposal.version, self._clock.now()
            )
        )
        if action.status is ActionStatus.SUCCEEDED:
            return _result(action)
        action.start()
        await self._repository.save(action)
        try:
            entry = await self._agenda.create_entry(
                action.action_id, _draft(proposal), action.idempotency_key
            )
            reminder = await self._reminders.schedule(
                entry.agenda_entry_id,
                entry.version,
                proposal.recommended_slot.starts_at - timedelta(minutes=reminder_lead_minutes),
                f"{action.idempotency_key}:reminder:v{entry.version}",
            )
        except Exception as exc:
            action.fail(type(exc).__name__)
            await self._repository.save(action)
            await self._audit_action(action, "FAILED")
            raise
        action.succeed(entry.agenda_entry_id, entry.version, reminder.reminder_id)
        await self._repository.save(action)
        await self._audit_action(action, "SUCCEEDED")
        return _result(action)

    async def request_undo(
        self, user_id: str, entry_id: UUID, entry_version: int
    ) -> UndoRequestView:
        action = await self._repository.add(
            ActionRequest.request_cancel(user_id, entry_id, entry_version, self._clock.now())
        )
        if action.agenda_entry_id is None or action.agenda_entry_version is None:
            raise RuntimeError("Undo Action omitted Agenda target")
        return UndoRequestView(
            action.action_id,
            action.agenda_entry_id,
            action.agenda_entry_version,
            action.confirmation_token,
            action.status.value,
        )

    async def confirm_undo(
        self, user_id: str, action_id: UUID, confirmation_token: str
    ) -> ActionResultView:
        action = await self._require(action_id)
        action.confirm_cancel(user_id, confirmation_token)
        if action.status is ActionStatus.SUCCEEDED:
            return _result(action)
        action.start()
        await self._repository.save(action)
        if action.agenda_entry_id is None or action.agenda_entry_version is None:
            raise RuntimeError("Undo Action omitted Agenda target")
        try:
            entry = await self._agenda.cancel_entry(
                action.action_id,
                action.agenda_entry_id,
                action.agenda_entry_version,
                action.idempotency_key,
            )
            await self._reminders.cancel_for_entry(
                action.agenda_entry_id, action.agenda_entry_version
            )
        except Exception as exc:
            action.fail(type(exc).__name__)
            await self._repository.save(action)
            await self._audit_action(action, "FAILED")
            raise
        action.succeed(entry.agenda_entry_id, entry.version)
        await self._repository.save(action)
        await self._audit_action(action, "SUCCEEDED")
        return _result(action)

    async def _audit_action(self, action: ActionRequest, outcome: str) -> None:
        if self._audit is None:
            return
        await self._audit.append(
            AuditEvent(
                "action-executed",
                action.user_id,
                f"action:{action.action_id}",
                outcome,
                self._clock.now(),
                {"action_type": action.action_type.value},
            )
        )

    async def _require(self, action_id: UUID) -> ActionRequest:
        action = await self._repository.get(action_id)
        if action is None:
            raise LookupError("Action does not exist")
        return action


def _draft(value: SchedulingProposalView) -> AgendaDraft:
    slot = value.recommended_slot
    if slot is None:
        raise ValueError("Proposal has no selected slot")
    kind = "EVENT" if value.candidate_kind == "EVENT" else "TASK_BLOCK"
    return AgendaDraft(
        kind,
        value.title,
        slot.starts_at,
        slot.ends_at,
        slot.timezone,
        value.source_refs,
        value.proposal_id,
    )


def _result(value: ActionRequest) -> ActionResultView:
    return ActionResultView(
        value.action_id,
        value.action_type.value,
        value.status.value,
        value.agenda_entry_id,
        value.agenda_entry_version,
        value.reminder_id,
    )
