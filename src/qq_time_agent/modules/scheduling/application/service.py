"""Side-effect-free scheduling orchestration over public read ports."""

from datetime import timedelta
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agenda.contracts import AgendaQueryPort
from qq_time_agent.modules.identity.contracts import UserPreferencesPort
from qq_time_agent.modules.scheduling.application.ports import ProposalRepository
from qq_time_agent.modules.scheduling.contracts import ProposalSlot, SchedulingProposalView
from qq_time_agent.modules.scheduling.domain.models import SchedulingProposal
from qq_time_agent.modules.scheduling.domain.planner import plan_event, plan_task
from qq_time_agent.modules.understanding.contracts import (
    CandidateQueryPort,
    EventCandidateView,
    TaskCandidateView,
)

PROPOSAL_LIFETIME_HOURS = 24
TASK_SEARCH_DAYS = 14


class SchedulingService:
    def __init__(
        self,
        candidates: CandidateQueryPort,
        preferences: UserPreferencesPort,
        agenda: AgendaQueryPort,
        repository: ProposalRepository,
        clock: Clock,
    ) -> None:
        self._candidates = candidates
        self._preferences = preferences
        self._agenda = agenda
        self._repository = repository
        self._clock = clock

    async def propose(self, user_id: str, candidate_id: UUID) -> SchedulingProposalView:
        existing = await self._repository.get_for_candidate(candidate_id)
        if existing is not None:
            return _view(existing)
        candidate = await self._candidates.get_candidate(candidate_id)
        if candidate is None:
            raise LookupError("candidate does not exist")
        preferences = await self._preferences.get_preferences(user_id)
        now = self._clock.now()
        if isinstance(candidate, EventCandidateView):
            busy = await self._agenda.get_busy_intervals(candidate.starts_at, candidate.ends_at)
            plan = plan_event(candidate, busy, preferences)
            kind = "EVENT"
        elif isinstance(candidate, TaskCandidateView):
            range_end = candidate.deadline or now + timedelta(days=TASK_SEARCH_DAYS)
            if range_end <= now:
                busy = ()
            else:
                busy = await self._agenda.get_busy_intervals(now, range_end)
            plan = plan_task(candidate, busy, preferences, now)
            kind = "TASK"
        else:
            raise TypeError("unsupported candidate view")
        proposal = SchedulingProposal.create(
            user_id,
            candidate.candidate_id,
            kind,
            candidate.title,
            plan.recommended,
            plan.alternatives,
            plan.conflicts,
            plan.rationale,
            plan.assumptions,
            candidate.source_refs,
            now + timedelta(hours=PROPOSAL_LIFETIME_HOURS),
            plan.snapshot,
        )
        return _view(await self._repository.add(proposal))

    async def get_proposal(self, proposal_id: UUID) -> SchedulingProposalView | None:
        value = await self._repository.get(proposal_id)
        return None if value is None else _view(value)

    async def confirm(
        self, user_id: str, proposal_id: UUID, version: int, confirmation_token: str
    ) -> SchedulingProposalView:
        value = await self._require_proposal(proposal_id)
        expected = value.version
        value.confirm(user_id, version, confirmation_token, self._clock.now())
        await self._repository.save(value, expected)
        return _view(value)

    async def revise(
        self, user_id: str, proposal_id: UUID, version: int, selected_slot: ProposalSlot
    ) -> SchedulingProposalView:
        value = await self._require_proposal(proposal_id)
        expected = value.version
        value.revise(user_id, version, selected_slot, self._clock.now())
        await self._repository.save(value, expected)
        return _view(value)

    async def reject(self, user_id: str, proposal_id: UUID, version: int) -> SchedulingProposalView:
        value = await self._require_proposal(proposal_id)
        expected = value.version
        value.reject(user_id, version, self._clock.now())
        await self._repository.save(value, expected)
        return _view(value)

    async def mark_executed(self, proposal_id: UUID, version: int) -> SchedulingProposalView:
        value = await self._require_proposal(proposal_id)
        expected = value.version
        value.mark_executed(version)
        await self._repository.save(value, expected)
        return _view(value)

    async def find_by_confirmation_token(self, token: str) -> SchedulingProposalView | None:
        parts = token.strip().split("-")
        if len(parts) != 2 or len(parts[0]) != 8 or not parts[1].isdigit():
            return None
        value = await self._repository.find_confirmable_by_prefix(parts[0], int(parts[1]))
        return None if value is None else _view(value)

    async def list_pending(self, limit: int) -> tuple[SchedulingProposalView, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("pending Proposal limit must be between 1 and 100")
        now = self._clock.now()
        return tuple(
            _view(value)
            for value in await self._repository.list_pending(limit)
            if value.expires_at > now
        )

    async def _require_proposal(self, proposal_id: UUID) -> SchedulingProposal:
        value = await self._repository.get(proposal_id)
        if value is None:
            raise LookupError("Proposal does not exist")
        return value


def _view(value: SchedulingProposal) -> SchedulingProposalView:
    return SchedulingProposalView(
        value.proposal_id,
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
        value.status.value,
    )
