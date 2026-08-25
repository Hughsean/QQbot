"""Classification, extraction, local validation, and low-confidence policy."""

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError

from qq_time_agent.modules.ai_gateway.contracts import (
    ModelFailure,
    ModelRoute,
    StructuredModelPort,
)
from qq_time_agent.modules.inbox.contracts import (
    ConversationContextPort,
    InboxSourcePort,
    InboxSourceView,
)
from qq_time_agent.modules.normalization.contracts import (
    NormalizedContentQueryPort,
    NormalizedContentView,
)
from qq_time_agent.modules.retrieval.contracts import RetrievalFilters, RetrievalPort
from qq_time_agent.modules.understanding.application.ports import CandidateRepository
from qq_time_agent.modules.understanding.application.prompts import (
    classification_request,
    extraction_request,
)
from qq_time_agent.modules.understanding.application.schemas import (
    ClassificationOutput,
    ExtractionOutput,
)
from qq_time_agent.modules.understanding.contracts import (
    CandidateDraft,
    CandidateKind,
    ClassificationDecision,
    ExtractionDecision,
    UnderstandingResult,
)
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
        retrieval: RetrievalPort | None = None,
        conversation: ConversationContextPort | None = None,
    ) -> None:
        self._content = content
        self._sources = sources
        self._model = model
        self._repository = repository
        self._temporal = temporal
        self._retrieval = retrieval
        self._conversation = conversation

    async def understand(self, inbox_item_id: UUID) -> UnderstandingResult:
        classification = await self.classify(inbox_item_id)
        if not classification.requires_extraction:
            return _classification_result(classification)
        extraction = await self.extract_candidate(
            inbox_item_id, classification.kind, classification.confidence
        )
        model_calls = classification.model_calls + extraction.model_calls
        if extraction.draft is None:
            return _review(
                inbox_item_id,
                extraction.confidence,
                extraction.review_reason or "invalid_model_output",
                model_calls,
            )
        result = await self.validate_and_save_candidate(inbox_item_id, extraction.draft)
        return replace(result, model_calls=model_calls)

    async def classify(self, inbox_item_id: UUID) -> ClassificationDecision:
        existing = await self._repository.get_for_inbox(inbox_item_id)
        if existing is not None:
            return ClassificationDecision(
                inbox_item_id, existing.kind, existing.candidate_id, existing.confidence, None, 0
            )
        content, source = await self._load_content(inbox_item_id)
        try:
            classification = await self._classify(
                content.subject, content.body, source.occurred_at, inbox_item_id
            )
        except (ValidationError, ModelFailure):
            return _classification_review(inbox_item_id, 0, "model_unavailable_or_invalid")
        if classification.kind == "IRRELEVANT":
            if classification.confidence < CONFIDENCE_THRESHOLD:
                return _classification_review(
                    inbox_item_id,
                    classification.confidence,
                    "low_classification_confidence",
                )
            return ClassificationDecision(
                inbox_item_id,
                CandidateKind.IRRELEVANT,
                None,
                classification.confidence,
                None,
                1,
            )
        if classification.kind == "NEEDS_REVIEW" or classification.temporal_ambiguity:
            return _classification_review(
                inbox_item_id, classification.confidence, "classification_ambiguous"
            )
        return ClassificationDecision(
            inbox_item_id,
            CandidateKind(classification.kind),
            None,
            classification.confidence,
            None,
            1,
        )

    async def extract_candidate(
        self,
        inbox_item_id: UUID,
        classification_kind: CandidateKind,
        classification_confidence: float,
    ) -> ExtractionDecision:
        if classification_kind not in {CandidateKind.EVENT, CandidateKind.TASK}:
            raise ValueError("only Event and Task classifications can be extracted")
        content, source = await self._load_content(inbox_item_id)
        route = (
            ModelRoute.REASONING
            if classification_confidence < CONFIDENCE_THRESHOLD
            else ModelRoute.FAST
        )
        try:
            extracted = await self._extract(
                content.subject, content.body, source.occurred_at, route, inbox_item_id
            )
        except (ValidationError, ModelFailure):
            return ExtractionDecision(None, classification_confidence, "invalid_model_output", 1)
        draft = _draft(extracted)
        return ExtractionDecision(draft, draft.confidence, None, 1)

    async def validate_and_save_candidate(
        self, inbox_item_id: UUID, draft: CandidateDraft
    ) -> UnderstandingResult:
        content, _ = await self._load_content(inbox_item_id)
        try:
            candidate = _candidate(
                inbox_item_id,
                content.source_ref or f"inbox:{inbox_item_id}:{content.source_hash}",
                draft,
                content.subject + "\n" + content.body,
                self._temporal.default_event_duration_minutes,
            )
        except ValueError:
            return _review(inbox_item_id, draft.confidence, "invalid_model_output", 0)
        if candidate.confidence < CONFIDENCE_THRESHOLD:
            return _review(inbox_item_id, candidate.confidence, "low_confidence", 0)
        candidate = await self._repository.add(candidate)
        return _candidate_result(candidate, 0)

    async def _load_content(
        self, inbox_item_id: UUID
    ) -> tuple[NormalizedContentView, InboxSourceView]:
        content = await self._content.get(inbox_item_id)
        source = await self._sources.get_source(inbox_item_id)
        if content is None or source is None or source.deleted:
            raise LookupError("active normalized Inbox content does not exist")
        return content, source

    async def _classify(
        self, subject: str, body: str, reference_time: datetime, inbox_item_id: UUID
    ) -> ClassificationOutput:
        context = await self._context(subject, body, reference_time, inbox_item_id)
        response = await self._model.invoke(
            classification_request(
                subject,
                body,
                reference_time,
                self._temporal.timezone,
                _alias(self._temporal.user_id),
                context,
            )
        )
        return ClassificationOutput.model_validate(response.output)

    async def _extract(
        self,
        subject: str,
        body: str,
        reference_time: datetime,
        route: ModelRoute,
        inbox_item_id: UUID,
    ) -> ExtractionOutput:
        context = await self._context(subject, body, reference_time, inbox_item_id)
        response = await self._model.invoke(
            extraction_request(
                subject,
                body,
                reference_time,
                self._temporal.timezone,
                _alias(self._temporal.user_id),
                route,
                context,
            )
        )
        return ExtractionOutput.model_validate(response.output)

    async def _context(
        self, subject: str, body: str, reference_time: datetime, inbox_item_id: UUID
    ) -> str:
        blocks: list[str] = []
        if self._conversation is not None:
            recent = await self._conversation.list_recent_conversation(
                self._temporal.user_id, reference_time, inbox_item_id
            )
            blocks.extend(
                f"[conversation] {item.occurred_at.isoformat()} {item.source_ref}\n"
                f"{item.subject}\n{item.body[:1800]}"
                for item in recent
            )
        if self._retrieval is not None:
            query = f"{subject}\n{body}"[:6000]
            chunks = await self._retrieval.retrieve(query, RetrievalFilters(), 5)
            blocks.extend(
                (
                    f"[knowledge] {item.occurred_at.isoformat()} {item.source_ref}\n"
                    f"{item.content[:1800]}"
                )
                for item in chunks
            )
        return "\n\n".join(blocks)[:12000]


def _candidate(
    inbox_item_id: UUID,
    source_ref: str | None,
    value: CandidateDraft,
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


def _draft(value: ExtractionOutput) -> CandidateDraft:
    return CandidateDraft(
        CandidateKind(value.kind),
        value.title,
        value.starts_at,
        value.ends_at,
        value.deadline,
        value.timezone,
        value.location,
        value.participants,
        value.estimated_duration_minutes,
        value.priority,
        value.allowed_windows,
        value.confidence,
        value.assumptions,
        value.evidence,
    )


def _classification_result(value: ClassificationDecision) -> UnderstandingResult:
    return UnderstandingResult(
        value.inbox_item_id,
        value.kind,
        value.candidate_id,
        value.confidence,
        value.review_reason,
        value.model_calls,
    )


def _classification_review(
    inbox_item_id: UUID, confidence: float, reason: str
) -> ClassificationDecision:
    return ClassificationDecision(
        inbox_item_id, CandidateKind.NEEDS_REVIEW, None, confidence, reason, 1
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
