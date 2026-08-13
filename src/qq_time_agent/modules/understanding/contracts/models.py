"""Stable structured candidates exposed by Understanding."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class CandidateKind(StrEnum):
    EVENT = "EVENT"
    TASK = "TASK"
    IRRELEVANT = "IRRELEVANT"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass(frozen=True, slots=True)
class EventCandidateView:
    candidate_id: UUID
    inbox_item_id: UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    location: str | None
    participants: tuple[str, ...]
    confidence: float
    assumptions: tuple[str, ...]
    evidence: tuple[str, ...]
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskCandidateView:
    candidate_id: UUID
    inbox_item_id: UUID
    title: str
    deadline: datetime | None
    estimated_duration_minutes: int | None
    priority: str | None
    allowed_windows: tuple[str, ...]
    confidence: float
    assumptions: tuple[str, ...]
    evidence: tuple[str, ...]
    source_refs: tuple[str, ...]


type CandidateView = EventCandidateView | TaskCandidateView


class CandidateQueryPort(Protocol):
    async def get_candidate(self, candidate_id: UUID) -> CandidateView | None: ...

    async def list_candidate_ids(self, limit: int) -> tuple[UUID, ...]: ...


@dataclass(frozen=True, slots=True)
class UnderstandingResult:
    inbox_item_id: UUID
    kind: CandidateKind
    candidate_id: UUID | None
    confidence: float
    review_reason: str | None
    model_calls: int


class UnderstandingUseCase(Protocol):
    async def understand(self, inbox_item_id: UUID) -> UnderstandingResult: ...
