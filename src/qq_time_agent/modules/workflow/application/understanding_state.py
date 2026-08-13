"""Bounded Understanding graph state and checkpoint conversion."""

from typing import TypedDict
from uuid import UUID

from qq_time_agent.modules.understanding.contracts import CandidateDraft
from qq_time_agent.modules.workflow.application.ports import WorkflowCheckpoint


class UnderstandingState(TypedDict):
    inbox_item_id: str
    phase: str
    result_kind: str | None
    candidate_id: str | None
    confidence: float | None
    review_reason: str | None
    model_calls: int
    version: int
    candidate_draft: CandidateDraft | None


def initial_checkpoint(inbox_item_id: UUID) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(inbox_item_id, "START", None, None, None, None, 0, 0)


def checkpoint_to_state(value: WorkflowCheckpoint) -> UnderstandingState:
    return UnderstandingState(
        inbox_item_id=str(value.inbox_item_id),
        phase=value.phase,
        result_kind=value.result_kind,
        candidate_id=None if value.candidate_id is None else str(value.candidate_id),
        confidence=value.confidence,
        review_reason=value.review_reason,
        model_calls=value.model_calls,
        version=value.version,
        candidate_draft=None,
    )


def optional_uuid(value: str | None) -> UUID | None:
    return None if value is None else UUID(value)
