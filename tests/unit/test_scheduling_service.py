from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaEntryView, BusyInterval
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.scheduling.application.service import SchedulingService
from qq_time_agent.modules.scheduling.contracts import confirmation_token
from qq_time_agent.modules.scheduling.domain.models import SchedulingProposal
from qq_time_agent.modules.understanding.contracts import (
    CandidateView,
    EventCandidateView,
    TaskCandidateView,
)


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, 1, tzinfo=UTC)


@dataclass
class Candidates:
    value: CandidateView | None

    async def get_candidate(self, candidate_id: UUID) -> CandidateView | None:
        if self.value is not None:
            assert self.value.candidate_id == candidate_id
        return self.value

    async def list_candidate_ids(self, limit: int) -> tuple[UUID, ...]:
        return () if self.value is None else (self.value.candidate_id,)


@dataclass
class UnknownCandidates:
    value: CandidateView

    async def get_candidate(self, candidate_id: UUID) -> CandidateView:
        return self.value

    async def list_candidate_ids(self, limit: int) -> tuple[UUID, ...]:
        return ()


@dataclass
class Preferences:
    async def get_preferences(self, user_id: str) -> UserPreferencesView:
        return UserPreferencesView(
            user_id,
            "Asia/Shanghai",
            time(9),
            time(18),
            time(12),
            time(13, 30),
            (0, 1, 2, 3, 4),
            30,
            60,
        )


@dataclass
class Agenda:
    busy: tuple[BusyInterval, ...] = ()

    async def get_busy_intervals(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[BusyInterval, ...]:
        return self.busy

    async def get_entry(self, entry_id: UUID) -> AgendaEntryView | None:
        return None


@dataclass
class Repository:
    value: SchedulingProposal | None = None

    async def add(self, proposal: SchedulingProposal) -> SchedulingProposal:
        if self.value is None:
            self.value = proposal
        return self.value

    async def get(self, proposal_id: UUID) -> SchedulingProposal | None:
        if self.value is not None and self.value.proposal_id == proposal_id:
            return self.value
        return None

    async def get_for_candidate(self, candidate_id: UUID) -> SchedulingProposal | None:
        if self.value is not None and self.value.candidate_id == candidate_id:
            return self.value
        return None

    async def save(self, proposal: SchedulingProposal, expected_version: int) -> None:
        assert self.value is proposal
        assert expected_version == proposal.version - 1

    async def find_confirmable_by_prefix(
        self, proposal_prefix: str, version: int
    ) -> SchedulingProposal | None:
        if (
            self.value is not None
            and self.value.proposal_id.hex.startswith(proposal_prefix)
            and self.value.version == version
        ):
            return self.value
        return None

    async def list_pending(self, limit: int) -> tuple[SchedulingProposal, ...]:
        return () if self.value is None else (self.value,)


def _task() -> TaskCandidateView:
    return TaskCandidateView(
        uuid4(),
        uuid4(),
        "写报告",
        datetime.fromisoformat("2026-08-14T17:00:00+08:00"),
        120,
        "NORMAL",
        (),
        0.9,
        (),
        ("写报告",),
        ("inbox:task",),
    )


@pytest.mark.asyncio
async def test_service_creates_idempotent_side_effect_free_proposal() -> None:
    candidate = _task()
    repository = Repository()
    service = SchedulingService(Candidates(candidate), Preferences(), Agenda(), repository, Clock())
    first = await service.propose("owner", candidate.candidate_id)
    second = await service.propose("owner", candidate.candidate_id)
    assert first == second
    assert first.candidate_kind == "TASK" and first.recommended_slot is not None
    assert first.status == "PENDING_CONFIRMATION"
    assert first.version == 1
    assert await service.get_proposal(first.proposal_id) == first


@pytest.mark.asyncio
async def test_service_rejects_missing_candidate() -> None:
    service = SchedulingService(Candidates(None), Preferences(), Agenda(), Repository(), Clock())
    with pytest.raises(LookupError, match="candidate"):
        await service.propose("owner", uuid4())


@pytest.mark.asyncio
async def test_service_plans_fixed_event_and_returns_missing_proposal() -> None:
    starts_at = datetime.fromisoformat("2026-08-13T10:00:00+08:00")
    candidate = EventCandidateView(
        uuid4(),
        uuid4(),
        "方案评审",
        starts_at,
        starts_at + timedelta(hours=1),
        "Asia/Shanghai",
        None,
        (),
        0.9,
        (),
        ("方案评审",),
        ("inbox:event",),
    )
    service = SchedulingService(
        Candidates(candidate), Preferences(), Agenda(), Repository(), Clock()
    )
    proposal = await service.propose("owner", candidate.candidate_id)
    assert proposal.candidate_kind == "EVENT"
    assert proposal.recommended_slot is not None
    assert await service.get_proposal(uuid4()) is None


@pytest.mark.asyncio
async def test_service_handles_expired_task_horizon_and_unknown_candidate_type() -> None:
    candidate = _task()
    expired = TaskCandidateView(
        candidate.candidate_id,
        candidate.inbox_item_id,
        candidate.title,
        datetime(2026, 8, 12, tzinfo=UTC),
        candidate.estimated_duration_minutes,
        candidate.priority,
        candidate.allowed_windows,
        candidate.confidence,
        candidate.assumptions,
        candidate.evidence,
        candidate.source_refs,
    )
    service = SchedulingService(Candidates(expired), Preferences(), Agenda(), Repository(), Clock())
    proposal = await service.propose("owner", expired.candidate_id)
    assert proposal.recommended_slot is None

    invalid = cast(CandidateView, object())
    invalid_service = SchedulingService(
        UnknownCandidates(invalid), Preferences(), Agenda(), Repository(), Clock()
    )
    with pytest.raises(TypeError, match="unsupported"):
        await invalid_service.propose("owner", uuid4())


@pytest.mark.asyncio
async def test_service_confirmation_revision_rejection_execution_and_queries() -> None:
    candidate = _task()
    repository = Repository()
    service = SchedulingService(Candidates(candidate), Preferences(), Agenda(), repository, Clock())
    initial = await service.propose("owner", candidate.candidate_id)
    assert await service.find_by_confirmation_token("invalid") is None
    assert (await service.list_pending(10))[0] == initial
    revised = await service.revise(
        "owner",
        initial.proposal_id,
        initial.version,
        initial.alternative_slots[0],
    )
    confirmed = await service.confirm(
        "owner",
        revised.proposal_id,
        revised.version,
        confirmation_token(revised.proposal_id, revised.version),
    )
    executed = await service.mark_executed(confirmed.proposal_id, confirmed.version)
    assert executed.status == "EXECUTED"
    with pytest.raises(ValueError, match="between"):
        await service.list_pending(0)
    with pytest.raises(LookupError, match="does not exist"):
        await service.reject("owner", uuid4(), 1)

    other_repository = Repository()
    other = SchedulingService(
        Candidates(candidate), Preferences(), Agenda(), other_repository, Clock()
    )
    pending = await other.propose("owner", candidate.candidate_id)
    rejected = await other.reject("owner", pending.proposal_id, pending.version)
    assert rejected.status == "REJECTED"
