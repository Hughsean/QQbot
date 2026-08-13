"""Stable, side-effect-free scheduling proposal views."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProposalSlot:
    starts_at: datetime
    ends_at: datetime
    timezone: str


@dataclass(frozen=True, slots=True)
class ProposalConflict:
    agenda_entry_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class SchedulingProposalView:
    proposal_id: UUID
    version: int
    user_id: str
    candidate_id: UUID
    candidate_kind: str
    title: str
    recommended_slot: ProposalSlot | None
    alternative_slots: tuple[ProposalSlot, ...]
    conflicts: tuple[ProposalConflict, ...]
    rationale: str
    assumptions: tuple[str, ...]
    source_refs: tuple[str, ...]
    expires_at: datetime
    status: str


class SchedulingPort(Protocol):
    async def propose(self, user_id: str, candidate_id: UUID) -> SchedulingProposalView: ...

    async def get_proposal(self, proposal_id: UUID) -> SchedulingProposalView | None: ...

    async def confirm(
        self, user_id: str, proposal_id: UUID, version: int, confirmation_token: str
    ) -> SchedulingProposalView: ...

    async def revise(
        self, user_id: str, proposal_id: UUID, version: int, selected_slot: ProposalSlot
    ) -> SchedulingProposalView: ...

    async def reject(
        self, user_id: str, proposal_id: UUID, version: int
    ) -> SchedulingProposalView: ...

    async def mark_executed(self, proposal_id: UUID, version: int) -> SchedulingProposalView: ...

    async def find_by_confirmation_token(self, token: str) -> SchedulingProposalView | None: ...

    async def list_pending(self, limit: int) -> tuple[SchedulingProposalView, ...]: ...


def confirmation_token(proposal_id: UUID, version: int) -> str:
    return f"{proposal_id.hex[:8]}-{version}"
