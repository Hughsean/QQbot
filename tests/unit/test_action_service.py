from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.actions.application.service import ActionService
from qq_time_agent.modules.actions.domain.models import ActionRequest
from qq_time_agent.modules.agenda.contracts import AgendaDraft, AgendaEntryRef
from qq_time_agent.modules.reminders.contracts import ReminderLease, ReminderRef, ReminderView
from qq_time_agent.modules.scheduling.contracts import ProposalSlot, SchedulingProposalView


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 20, tzinfo=UTC)


@dataclass
class Repository:
    values: dict[UUID, ActionRequest] = field(default_factory=dict)
    keys: dict[str, UUID] = field(default_factory=dict)

    async def add(self, value: ActionRequest) -> ActionRequest:
        action_id = self.keys.get(value.idempotency_key)
        if action_id is not None:
            return self.values[action_id]
        self.keys[value.idempotency_key] = value.action_id
        self.values[value.action_id] = value
        return value

    async def get(self, action_id: UUID) -> ActionRequest | None:
        return self.values.get(action_id)

    async def save(self, value: ActionRequest) -> None:
        self.values[value.action_id] = value


@dataclass
class Agenda:
    creates: int = 0
    cancels: int = 0
    fail_create: bool = False
    entry_id: UUID = field(default_factory=uuid4)

    async def create_entry(
        self, action_id: UUID, draft: AgendaDraft, idempotency_key: str
    ) -> AgendaEntryRef:
        if self.fail_create:
            raise RuntimeError("synthetic agenda failure")
        self.creates += 1
        return AgendaEntryRef(self.entry_id, 1)

    async def revise_entry(
        self,
        action_id: UUID,
        entry_id: UUID,
        expected_version: int,
        draft: AgendaDraft,
        idempotency_key: str,
    ) -> AgendaEntryRef:
        return AgendaEntryRef(entry_id, expected_version + 1)

    async def cancel_entry(
        self, action_id: UUID, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> AgendaEntryRef:
        self.cancels += 1
        return AgendaEntryRef(entry_id, expected_version + 1)

    async def complete_entry(
        self, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> AgendaEntryRef:
        return AgendaEntryRef(entry_id, expected_version + 1)


@dataclass
class Reminders:
    schedules: int = 0
    cancelled: int = 0
    reminder_id: UUID = field(default_factory=uuid4)

    async def schedule(
        self, entry_id: UUID, entry_version: int, due_at: datetime, idempotency_key: str
    ) -> ReminderRef:
        self.schedules += 1
        return ReminderRef(self.reminder_id)

    async def cancel_for_entry(self, entry_id: UUID, expected_version: int) -> int:
        self.cancelled += 1
        return 1

    async def snooze(
        self,
        reminder_id: UUID,
        delay: timedelta,
        now: datetime,
        *,
        expected_occurrence: int,
    ) -> ReminderView:
        del reminder_id, delay, now, expected_occurrence

    async def reschedule(self, reminder_id: UUID, due_at: datetime, now: datetime) -> ReminderView:
        raise NotImplementedError

    async def list_for_entry(self, entry_id: UUID) -> tuple[ReminderView, ...]:
        return ()

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> tuple[ReminderLease, ...]:
        return ()

    async def mark_sent(self, lease: ReminderLease, delivery_ref: str) -> None:
        return None

    async def mark_failed(
        self, lease: ReminderLease, failure_class: str, next_attempt_at: datetime | None
    ) -> None:
        return None


def _proposal() -> SchedulingProposalView:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    return SchedulingProposalView(
        uuid4(),
        2,
        "owner",
        uuid4(),
        "TASK",
        "写报告",
        ProposalSlot(start, start + timedelta(hours=1), "Asia/Shanghai"),
        (),
        (),
        "满足约束",
        (),
        ("inbox:test",),
        start + timedelta(days=1),
        "CONFIRMED",
    )


@pytest.mark.asyncio
async def test_confirmed_action_is_idempotent_and_schedules_one_reminder() -> None:
    repository = Repository()
    agenda = Agenda()
    reminders = Reminders()
    service = ActionService(repository, agenda, reminders, Clock())
    proposal = _proposal()
    first = await service.execute_confirmed(proposal, 15)
    second = await service.execute_confirmed(proposal, 15)
    assert first == second
    assert agenda.creates == 1 and reminders.schedules == 1
    assert first.agenda_entry_id == agenda.entry_id


@pytest.mark.asyncio
async def test_undo_requires_separate_token_and_cancels_reminder() -> None:
    repository = Repository()
    agenda = Agenda()
    reminders = Reminders()
    service = ActionService(repository, agenda, reminders, Clock())
    request = await service.request_undo("owner", agenda.entry_id, 1)
    with pytest.raises(ValueError, match="token"):
        await service.confirm_undo("owner", request.action_id, "wrong")
    result = await service.confirm_undo("owner", request.action_id, request.confirmation_token)
    assert result.status == "SUCCEEDED"
    assert agenda.cancels == 1 and reminders.cancelled == 1


@pytest.mark.asyncio
async def test_action_policy_validation_failure_and_retry_recovery() -> None:
    repository = Repository()
    agenda = Agenda(fail_create=True)
    service = ActionService(repository, agenda, Reminders(), Clock())
    invalid = replace(_proposal(), status="PENDING_CONFIRMATION")
    with pytest.raises(PermissionError):
        await service.execute_confirmed(invalid, 15)
    with pytest.raises(ValueError, match="non-negative"):
        await service.execute_confirmed(_proposal(), -1)
    with pytest.raises(RuntimeError, match="synthetic"):
        await service.execute_confirmed(_proposal(), 15)
    failed = next(iter(repository.values.values()))
    assert failed.status.value == "FAILED" and failed.failure_class == "RuntimeError"
    agenda.fail_create = False
    result = await service.execute_confirmed(_proposal_with_id(failed.proposal_id), 15)
    assert result.status == "SUCCEEDED"
    with pytest.raises(LookupError, match="does not exist"):
        await service.confirm_undo("owner", uuid4(), "none")


def _proposal_with_id(proposal_id: UUID | None) -> SchedulingProposalView:
    value = _proposal()
    assert proposal_id is not None
    return SchedulingProposalView(
        proposal_id,
        value.version,
        value.user_id,
        value.candidate_id,
        value.candidate_kind,
        value.title,
        value.recommended_slot,
        value.alternative_slots,
        value.conflicts,
        value.rationale,
        value.assumptions,
        value.source_refs,
        value.expires_at,
        value.status,
    )
