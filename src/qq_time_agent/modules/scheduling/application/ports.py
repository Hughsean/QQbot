"""Private Scheduling Proposal persistence port."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.scheduling.domain.models import SchedulingProposal


class ProposalRepository(Protocol):
    async def add(self, proposal: SchedulingProposal) -> SchedulingProposal: ...

    async def get(self, proposal_id: UUID) -> SchedulingProposal | None: ...

    async def get_for_candidate(self, candidate_id: UUID) -> SchedulingProposal | None: ...

    async def save(self, proposal: SchedulingProposal, expected_version: int) -> None: ...

    async def find_confirmable_by_prefix(
        self, proposal_prefix: str, version: int
    ) -> SchedulingProposal | None: ...

    async def list_pending(self, limit: int) -> tuple[SchedulingProposal, ...]: ...
