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
class ClassificationDecision:
    inbox_item_id: UUID
    kind: CandidateKind
    candidate_id: UUID | None
    confidence: float
    review_reason: str | None
    model_calls: int

    @property
    def requires_extraction(self) -> bool:
        return (
            self.kind in {CandidateKind.EVENT, CandidateKind.TASK}
            and self.candidate_id is None
            and self.review_reason is None
        )


@dataclass(frozen=True, slots=True)
class CandidateDraft:
    kind: CandidateKind
    title: str
    starts_at: datetime | None
    ends_at: datetime | None
    deadline: datetime | None
    timezone: str
    location: str | None
    participants: tuple[str, ...]
    estimated_duration_minutes: int | None
    priority: str | None
    allowed_windows: tuple[str, ...]
    confidence: float
    assumptions: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExtractionDecision:
    draft: CandidateDraft | None
    confidence: float
    review_reason: str | None
    model_calls: int


@dataclass(frozen=True, slots=True)
class UnderstandingResult:
    inbox_item_id: UUID
    kind: CandidateKind
    candidate_id: UUID | None
    confidence: float
    review_reason: str | None
    model_calls: int


class UnderstandingUseCase(Protocol):
    async def classify(self, inbox_item_id: UUID) -> ClassificationDecision: ...

    async def extract_candidate(
        self,
        inbox_item_id: UUID,
        classification_kind: CandidateKind,
        classification_confidence: float,
    ) -> ExtractionDecision: ...

    async def validate_and_save_candidate(
        self, inbox_item_id: UUID, draft: CandidateDraft
    ) -> UnderstandingResult: ...
