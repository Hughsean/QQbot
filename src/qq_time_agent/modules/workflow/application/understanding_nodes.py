"""Thin nodes for the bounded Understanding workflow."""

from uuid import UUID

from qq_time_agent.modules.inbox.contracts import InboxProcessingPort, InboxSourcePort
from qq_time_agent.modules.understanding.contracts import (
    CandidateKind,
    ExtractionDecision,
    UnderstandingResult,
    UnderstandingUseCase,
)
from qq_time_agent.modules.workflow.application.ports import (
    WorkflowCheckpoint,
    WorkflowCheckpointRepository,
)
from qq_time_agent.modules.workflow.application.understanding_state import (
    UnderstandingState,
    checkpoint_to_state,
    optional_uuid,
)


class UnderstandingNodes:
    def __init__(
        self,
        understanding: UnderstandingUseCase,
        inbox: InboxProcessingPort,
        checkpoints: WorkflowCheckpointRepository,
        sources: InboxSourcePort | None = None,
    ) -> None:
        self._understanding = understanding
        self._inbox = inbox
        self._checkpoints = checkpoints
        self._sources = sources

    async def classify(self, state: UnderstandingState) -> UnderstandingState:
        inbox_item_id = UUID(state["inbox_item_id"])
        decision = await self._understanding.classify(inbox_item_id)
        checkpoint = WorkflowCheckpoint(
            inbox_item_id,
            "CLASSIFIED",
            decision.kind.value,
            decision.candidate_id,
            decision.confidence,
            decision.review_reason,
            decision.model_calls,
            state["version"] + 1,
            await self._source_ref(inbox_item_id),
        )
        await self._checkpoints.save(checkpoint)
        return checkpoint_to_state(checkpoint)

    async def extract_candidate(self, state: UnderstandingState) -> UnderstandingState:
        inbox_item_id = UUID(state["inbox_item_id"])
        raw_kind = state["result_kind"]
        confidence = state["confidence"]
        if raw_kind is None or confidence is None:
            raise RuntimeError("classified workflow is missing extraction inputs")
        decision = await self._understanding.extract_candidate(
            inbox_item_id, CandidateKind(raw_kind), confidence
        )
        result_kind = (
            CandidateKind.NEEDS_REVIEW.value
            if decision.draft is None
            else decision.draft.kind.value
        )
        return _extracted_state(state, decision, result_kind)

    async def validate_candidate(self, state: UnderstandingState) -> UnderstandingState:
        draft = state["candidate_draft"]
        if draft is None:
            raise RuntimeError("extracted workflow is missing candidate draft")
        result = await self._understanding.validate_and_save_candidate(
            UUID(state["inbox_item_id"]), draft
        )
        return _validated_state(state, result)

    async def persist_decision(self, state: UnderstandingState) -> UnderstandingState:
        inbox_item_id = UUID(state["inbox_item_id"])
        checkpoint = WorkflowCheckpoint(
            inbox_item_id,
            "DECIDED",
            state["result_kind"],
            optional_uuid(state["candidate_id"]),
            state["confidence"],
            state["review_reason"],
            state["model_calls"],
            state["version"] + 1,
            await self._source_ref(inbox_item_id),
        )
        await self._checkpoints.save(checkpoint)
        return checkpoint_to_state(checkpoint)

    async def apply_disposition(self, state: UnderstandingState) -> UnderstandingState:
        inbox_item_id = UUID(state["inbox_item_id"])
        kind = _required_kind(state["result_kind"])
        if kind in {CandidateKind.EVENT, CandidateKind.TASK}:
            await self._inbox.mark_understood(inbox_item_id)
        elif kind is CandidateKind.IRRELEVANT:
            await self._inbox.mark_ignored(inbox_item_id)
        else:
            await self._inbox.mark_needs_review(inbox_item_id)
        checkpoint = WorkflowCheckpoint(
            inbox_item_id,
            "COMPLETE",
            kind.value,
            optional_uuid(state["candidate_id"]),
            state["confidence"],
            state["review_reason"],
            state["model_calls"],
            state["version"] + 1,
            await self._source_ref(inbox_item_id),
        )
        await self._checkpoints.save(checkpoint)
        return checkpoint_to_state(checkpoint)

    async def _source_ref(self, inbox_item_id: UUID) -> str | None:
        if self._sources is None:
            return None
        source = await self._sources.get_source(inbox_item_id)
        return None if source is None else source.source_ref


def _required_kind(value: str | None) -> CandidateKind:
    if value is None:
        raise RuntimeError("decided workflow is missing result kind")
    return CandidateKind(value)


def _extracted_state(
    state: UnderstandingState, decision: ExtractionDecision, result_kind: str
) -> UnderstandingState:
    return UnderstandingState(
        inbox_item_id=state["inbox_item_id"],
        phase=state["phase"],
        result_kind=result_kind,
        candidate_id=state["candidate_id"],
        confidence=decision.confidence,
        review_reason=decision.review_reason,
        model_calls=state["model_calls"] + decision.model_calls,
        version=state["version"],
        candidate_draft=decision.draft,
    )


def _validated_state(state: UnderstandingState, result: UnderstandingResult) -> UnderstandingState:
    return UnderstandingState(
        inbox_item_id=state["inbox_item_id"],
        phase=state["phase"],
        result_kind=result.kind.value,
        candidate_id=None if result.candidate_id is None else str(result.candidate_id),
        confidence=result.confidence,
        review_reason=result.review_reason,
        model_calls=state["model_calls"],
        version=state["version"],
        candidate_draft=None,
    )
