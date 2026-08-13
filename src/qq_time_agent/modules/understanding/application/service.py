"""Classification, extraction, local validation, and low-confidence policy."""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError

from qq_time_agent.modules.ai_gateway.contracts import (
    ModelFailure,
    ModelRoute,
    StructuredModelPort,
)
from qq_time_agent.modules.inbox.contracts import InboxSourcePort
from qq_time_agent.modules.normalization.contracts import NormalizedContentQueryPort
from qq_time_agent.modules.understanding.application.ports import CandidateRepository
from qq_time_agent.modules.understanding.application.prompts import (
    classification_request,
    extraction_request,
)
from qq_time_agent.modules.understanding.application.schemas import (
    ClassificationOutput,
    ExtractionOutput,
)
from qq_time_agent.modules.understanding.contracts import CandidateKind, UnderstandingResult
from qq_time_agent.modules.understanding.domain.candidates import Candidate

CONFIDENCE_THRESHOLD = 0.75


@dataclass(frozen=True, slots=True)
class TemporalContext:
    timezone: str
    user_id: str
    default_event_duration_minutes: int = 30

    def __post_init__(self) -> None:
        if self.default_event_duration_minutes < 1:
            raise ValueError("default Event duration must be positive")


class UnderstandingService:
    def __init__(
        self,
        content: NormalizedContentQueryPort,
        sources: InboxSourcePort,
        model: StructuredModelPort,
        repository: CandidateRepository,
        temporal: TemporalContext,
    ) -> None:
        self._content = content
        self._sources = sources
        self._model = model
        self._repository = repository
        self._temporal = temporal

    async def understand(self, inbox_item_id: UUID) -> UnderstandingResult:
        existing = await self._repository.get_for_inbox(inbox_item_id)
        if existing is not None:
            return _candidate_result(existing, 0)
        content = await self._content.get(inbox_item_id)
        source = await self._sources.get_source(inbox_item_id)
        if content is None or source is None or source.deleted:
            raise LookupError("active normalized Inbox content does not exist")
        try:
            classification = await self._classify(content.subject, content.body, source.occurred_at)
        except (ValidationError, ModelFailure):
            return _review(inbox_item_id, 0, "model_unavailable_or_invalid", 1)
        if classification.kind == "IRRELEVANT":
            if classification.confidence < CONFIDENCE_THRESHOLD:
                return _review(
                    inbox_item_id,
                    classification.confidence,
                    "low_classification_confidence",
                    1,
                )
            return UnderstandingResult(
                inbox_item_id,
                CandidateKind.IRRELEVANT,
                None,
                classification.confidence,
                None,
                1,
            )
        if classification.kind == "NEEDS_REVIEW" or classification.temporal_ambiguity:
            return _review(inbox_item_id, classification.confidence, "classification_ambiguous", 1)
        route = (
            ModelRoute.REASONING
            if classification.confidence < CONFIDENCE_THRESHOLD
            else ModelRoute.FAST
        )
        try:
            extracted = await self._extract(
                content.subject, content.body, source.occurred_at, route
            )
            candidate = _candidate(
                inbox_item_id,
                content.source_ref or f"inbox:{inbox_item_id}:{content.source_hash}",
                extracted,
                content.subject + "\n" + content.body,
                self._temporal.default_event_duration_minutes,
            )
        except (ValidationError, ValueError, ModelFailure):
            return _review(inbox_item_id, classification.confidence, "invalid_model_output", 2)
        if candidate.confidence < CONFIDENCE_THRESHOLD:
            return _review(inbox_item_id, candidate.confidence, "low_confidence", 2)
        candidate = await self._repository.add(candidate)
        return _candidate_result(candidate, 2)

    async def _classify(
        self, subject: str, body: str, reference_time: datetime
    ) -> ClassificationOutput:
        response = await self._model.invoke(
            classification_request(
                subject,
                body,
                reference_time,
                self._temporal.timezone,
                _alias(self._temporal.user_id),
            )
        )
        return ClassificationOutput.model_validate(response.output)

    async def _extract(
        self, subject: str, body: str, reference_time: datetime, route: ModelRoute
    ) -> ExtractionOutput:
        response = await self._model.invoke(
            extraction_request(
                subject,
                body,
                reference_time,
                self._temporal.timezone,
                _alias(self._temporal.user_id),
                route,
            )
        )
        return ExtractionOutput.model_validate(response.output)


def _candidate(
    inbox_item_id: UUID,
    source_ref: str | None,
    value: ExtractionOutput,
    body: str,
    default_event_duration_minutes: int,
) -> Candidate:
    if source_ref is None:
        raise ValueError("normalized source reference is required")
    if any(evidence not in body for evidence in value.evidence):
        raise ValueError("candidate evidence must occur in normalized content")
    ends_at = value.ends_at
    assumptions = value.assumptions
    if value.kind == "EVENT" and ends_at is None:
        if value.starts_at is None:
            raise ValueError("Event start is missing")
        ends_at = value.starts_at + timedelta(minutes=default_event_duration_minutes)
        assumptions += (f"未提供持续时间, 使用默认 {default_event_duration_minutes} 分钟",)
    return Candidate.create(
        inbox_item_id,
        CandidateKind(value.kind),
        value.title,
        value.starts_at,
        ends_at,
        value.deadline,
        value.timezone,
        value.location,
        value.participants,
        value.estimated_duration_minutes,
        value.priority,
        value.allowed_windows,
        value.confidence,
        assumptions,
        value.evidence,
        (source_ref,),
    )


def _candidate_result(value: Candidate, model_calls: int) -> UnderstandingResult:
    return UnderstandingResult(
        value.inbox_item_id, value.kind, value.candidate_id, value.confidence, None, model_calls
    )


def _review(inbox_item_id: UUID, confidence: float, reason: str, calls: int) -> UnderstandingResult:
    return UnderstandingResult(
        inbox_item_id, CandidateKind.NEEDS_REVIEW, None, confidence, reason, calls
    )


def _alias(user_id: str) -> str:
    return "user-" + hashlib.sha256(user_id.encode()).hexdigest()[:16]
