"""Read-only access to pending proposals for Agent context."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.scheduling.application.ports import ProposalRepository
from qq_time_agent.modules.scheduling.contracts import SchedulingProposalView
from qq_time_agent.modules.scheduling.domain.models import SchedulingProposal


class PendingProposalQueryService:
    def __init__(self, repository: ProposalRepository, clock: Clock) -> None:
        self._repository = repository
        self._clock = clock

    async def list_pending(self, limit: int) -> tuple[SchedulingProposalView, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("pending Proposal limit must be between 1 and 100")
        now = self._clock.now()
        return tuple(
            _view(value)
            for value in await self._repository.list_pending(limit)
            if value.expires_at > now
        )


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
