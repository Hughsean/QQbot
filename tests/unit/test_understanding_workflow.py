from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.understanding.contracts import (
    CandidateDraft,
    CandidateKind,
    ClassificationDecision,
    ExtractionDecision,
    UnderstandingResult,
)
from qq_time_agent.modules.workflow.application.ports import WorkflowCheckpoint
from qq_time_agent.modules.workflow.application.understanding_graph import (
    UnderstandingWorkflow,
)


@dataclass
class Understanding:
    classification: ClassificationDecision
    extraction: ExtractionDecision | None = None
    validation: UnderstandingResult | None = None
    calls: list[str] = field(default_factory=list)

    async def classify(self, inbox_item_id: UUID) -> ClassificationDecision:
        assert inbox_item_id == self.classification.inbox_item_id
        self.calls.append("classify")
        return self.classification

    async def extract_candidate(
        self,
        inbox_item_id: UUID,
        classification_kind: CandidateKind,
        classification_confidence: float,
    ) -> ExtractionDecision:
        assert inbox_item_id == self.classification.inbox_item_id
        assert classification_kind == self.classification.kind
        assert classification_confidence == self.classification.confidence
        assert self.extraction is not None
        self.calls.append("extract_candidate")
        return self.extraction

    async def validate_and_save_candidate(
        self, inbox_item_id: UUID, draft: CandidateDraft
    ) -> UnderstandingResult:
        assert inbox_item_id == self.classification.inbox_item_id
        assert self.extraction is not None and draft == self.extraction.draft
        assert self.validation is not None
        self.calls.append("validate_candidate")
        return self.validation


@dataclass
class Inbox:
    transitions: list[tuple[str, UUID]] = field(default_factory=list)

    async def mark_normalized(self, inbox_item_id: UUID) -> None:
        self.transitions.append(("NORMALIZED", inbox_item_id))

    async def mark_understood(self, inbox_item_id: UUID) -> None:
        self.transitions.append(("UNDERSTOOD", inbox_item_id))

    async def mark_needs_review(self, inbox_item_id: UUID) -> None:
        self.transitions.append(("NEEDS_REVIEW", inbox_item_id))

    async def mark_ignored(self, inbox_item_id: UUID) -> None:
        self.transitions.append(("IGNORED", inbox_item_id))

    async def mark_proposed(self, inbox_item_id: UUID) -> None:
        self.transitions.append(("PROPOSED", inbox_item_id))

    async def mark_completed(self, inbox_item_id: UUID) -> None:
        self.transitions.append(("COMPLETED", inbox_item_id))


@dataclass
class Checkpoints:
    value: WorkflowCheckpoint | None = None
    writes: list[WorkflowCheckpoint] = field(default_factory=list)

    async def get(self, inbox_item_id: UUID) -> WorkflowCheckpoint | None:
        if self.value is not None:
            assert self.value.inbox_item_id == inbox_item_id
        return self.value

    async def save(self, checkpoint: WorkflowCheckpoint) -> None:
        self.value = checkpoint
        self.writes.append(checkpoint)


def _draft(kind: CandidateKind) -> CandidateDraft:
    return CandidateDraft(
        kind,
        "安排",
        None,
        None,
        None,
        "Asia/Shanghai",
        None,
        (),
        30,
        "NORMAL",
        (),
        0.9,
        (),
        ("安排",),
    )


def _understanding(item_id: UUID, kind: CandidateKind) -> Understanding:
    candidate_id = uuid4() if kind in {CandidateKind.EVENT, CandidateKind.TASK} else None
    classification = ClassificationDecision(item_id, kind, None, 0.9, None, 1)
    if kind not in {CandidateKind.EVENT, CandidateKind.TASK}:
        return Understanding(classification)
    draft = _draft(kind)
    return Understanding(
        classification,
        ExtractionDecision(draft, 0.9, None, 1),
        UnderstandingResult(item_id, kind, candidate_id, 0.9, None, 0),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,transition,expected_calls",
    [
        (CandidateKind.EVENT, "UNDERSTOOD", 2),
        (CandidateKind.TASK, "UNDERSTOOD", 2),
        (CandidateKind.IRRELEVANT, "IGNORED", 1),
        (CandidateKind.NEEDS_REVIEW, "NEEDS_REVIEW", 1),
    ],
)
async def test_staged_graph_applies_only_inbox_disposition(
    kind: CandidateKind, transition: str, expected_calls: int
) -> None:
    item_id = uuid4()
    use_case = _understanding(item_id, kind)
    inbox = Inbox()
    checkpoints = Checkpoints()
    workflow = UnderstandingWorkflow(use_case, inbox, checkpoints)
    result = await workflow.run_understanding(item_id)
    assert result.status == "COMPLETE" and result.model_calls == expected_calls
    assert inbox.transitions == [(transition, item_id)]
    assert [write.phase for write in checkpoints.writes] == [
        "CLASSIFIED",
        "DECIDED",
        "COMPLETE",
    ]


@pytest.mark.asyncio
async def test_graph_resumes_after_classification_without_second_classification() -> None:
    item_id = uuid4()
    use_case = _understanding(item_id, CandidateKind.TASK)
    checkpoints = Checkpoints(
        WorkflowCheckpoint(item_id, "CLASSIFIED", "TASK", None, 0.9, None, 1, 1)
    )
    workflow = UnderstandingWorkflow(use_case, Inbox(), checkpoints)
    result = await workflow.run_understanding(item_id)
    assert result.status == "COMPLETE" and result.model_calls == 2
    assert use_case.calls == ["extract_candidate", "validate_candidate"]
    assert [write.phase for write in checkpoints.writes] == ["DECIDED", "COMPLETE"]


@pytest.mark.asyncio
async def test_existing_candidate_skips_extraction_and_validation() -> None:
    item_id = uuid4()
    candidate_id = uuid4()
    use_case = Understanding(
        ClassificationDecision(item_id, CandidateKind.EVENT, candidate_id, 0.9, None, 0)
    )
    inbox = Inbox()
    workflow = UnderstandingWorkflow(use_case, inbox, Checkpoints())
    result = await workflow.run_understanding(item_id)
    assert result.candidate_id == candidate_id and result.model_calls == 0
    assert use_case.calls == ["classify"]
    assert inbox.transitions == [("UNDERSTOOD", item_id)]


@pytest.mark.asyncio
async def test_graph_resumes_after_decision_without_model_or_validation_call() -> None:
    item_id = uuid4()
    candidate_id = uuid4()
    use_case = _understanding(item_id, CandidateKind.TASK)
    inbox = Inbox()
    checkpoints = Checkpoints(
        WorkflowCheckpoint(item_id, "DECIDED", "TASK", candidate_id, 0.9, None, 2, 2)
    )
    workflow = UnderstandingWorkflow(use_case, inbox, checkpoints)
    result = await workflow.run_understanding(item_id)
    assert result.status == "COMPLETE"
    assert use_case.calls == [] and inbox.transitions == [("UNDERSTOOD", item_id)]


@pytest.mark.asyncio
async def test_invalid_extraction_routes_to_review_without_validation() -> None:
    item_id = uuid4()
    use_case = Understanding(
        ClassificationDecision(item_id, CandidateKind.TASK, None, 0.9, None, 1),
        ExtractionDecision(None, 0.9, "invalid_model_output", 1),
    )
    inbox = Inbox()
    workflow = UnderstandingWorkflow(use_case, inbox, Checkpoints())
    result = await workflow.run_understanding(item_id)
    assert result.review_reason == "invalid_model_output" and result.model_calls == 2
    assert use_case.calls == ["classify", "extract_candidate"]
    assert inbox.transitions == [("NEEDS_REVIEW", item_id)]


@pytest.mark.asyncio
async def test_complete_graph_is_idempotent_and_has_no_side_effect_tools() -> None:
    item_id = uuid4()
    use_case = _understanding(item_id, CandidateKind.IRRELEVANT)
    inbox = Inbox()
    checkpoints = Checkpoints(
        WorkflowCheckpoint(item_id, "COMPLETE", "IRRELEVANT", None, 1, None, 1, 3)
    )
    workflow = UnderstandingWorkflow(use_case, inbox, checkpoints)
    result = await workflow.run_understanding(item_id)
    assert result.status == "COMPLETE"
    assert use_case.calls == [] and inbox.transitions == [] and checkpoints.writes == []
