"""Public candidate query mapping without exposing domain objects."""

from uuid import UUID

from qq_time_agent.modules.understanding.application.ports import CandidateRepository
from qq_time_agent.modules.understanding.contracts import (
    CandidateKind,
    CandidateView,
    EventCandidateView,
    TaskCandidateView,
)
from qq_time_agent.modules.understanding.domain.candidates import Candidate


class CandidateQueryService:
    def __init__(self, repository: CandidateRepository) -> None:
        self._repository = repository

    async def get_candidate(self, candidate_id: UUID) -> CandidateView | None:
        value = await self._repository.get(candidate_id)
        return None if value is None else _view(value)

    async def list_candidate_ids(self, limit: int) -> tuple[UUID, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("candidate query limit must be between 1 and 100")
        return await self._repository.list_ids(limit)


def _view(value: Candidate) -> CandidateView:
    if value.kind is CandidateKind.EVENT:
        if value.starts_at is None or value.ends_at is None:
            raise RuntimeError("stored Event candidate is invalid")
        return EventCandidateView(
            value.candidate_id,
            value.inbox_item_id,
            value.title,
            value.starts_at,
            value.ends_at,
            value.timezone,
            value.location,
            value.participants,
            value.confidence,
            value.assumptions,
            value.evidence,
            value.source_refs,
        )
    return TaskCandidateView(
        value.candidate_id,
        value.inbox_item_id,
        value.title,
        value.deadline,
        value.estimated_duration_minutes,
        value.priority,
        value.allowed_windows,
        value.confidence,
        value.assumptions,
        value.evidence,
        value.source_refs,
    )
