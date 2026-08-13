from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.understanding.contracts import (
    CandidateKind,
    UnderstandingResult,
)
from qq_time_agent.modules.workflow.application.ports import WorkflowCheckpoint
from qq_time_agent.modules.workflow.application.understanding_graph import (
    UnderstandingWorkflow,
)


@dataclass
class Understanding:
    result: UnderstandingResult
    calls: int = 0

    async def understand(self, inbox_item_id: UUID) -> UnderstandingResult:
        assert inbox_item_id == self.result.inbox_item_id
        self.calls += 1
        return self.result


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,transition",
    [
        (CandidateKind.EVENT, "UNDERSTOOD"),
        (CandidateKind.TASK, "UNDERSTOOD"),
        (CandidateKind.IRRELEVANT, "IGNORED"),
        (CandidateKind.NEEDS_REVIEW, "NEEDS_REVIEW"),
    ],
)
async def test_bounded_graph_applies_only_inbox_disposition(
    kind: CandidateKind, transition: str
) -> None:
    item_id = uuid4()
    candidate_id = uuid4() if kind in {CandidateKind.EVENT, CandidateKind.TASK} else None
    use_case = Understanding(UnderstandingResult(item_id, kind, candidate_id, 0.9, None, 2))
    inbox = Inbox()
    checkpoints = Checkpoints()
    workflow = UnderstandingWorkflow(use_case, inbox, checkpoints)
    result = await workflow.run_understanding(item_id)
    assert result.status == "COMPLETE"
    assert inbox.transitions == [(transition, item_id)]
    assert [write.phase for write in checkpoints.writes] == ["DECIDED", "COMPLETE"]
    assert use_case.calls == 1


@pytest.mark.asyncio
async def test_graph_resumes_after_decision_without_second_model_call() -> None:
    item_id = uuid4()
    candidate_id = uuid4()
    use_case = Understanding(
        UnderstandingResult(item_id, CandidateKind.TASK, candidate_id, 0.9, None, 2)
    )
    inbox = Inbox()
    checkpoints = Checkpoints(
        WorkflowCheckpoint(item_id, "DECIDED", "TASK", candidate_id, 0.9, None, 2, 1)
    )
    workflow = UnderstandingWorkflow(use_case, inbox, checkpoints)
    result = await workflow.run_understanding(item_id)
    assert result.status == "COMPLETE"
    assert use_case.calls == 0
    assert inbox.transitions == [("UNDERSTOOD", item_id)]


@pytest.mark.asyncio
async def test_complete_graph_is_idempotent_and_has_no_side_effect_tools() -> None:
    item_id = uuid4()
    use_case = Understanding(
        UnderstandingResult(item_id, CandidateKind.IRRELEVANT, None, 1, None, 1)
    )
    inbox = Inbox()
    checkpoints = Checkpoints(
        WorkflowCheckpoint(item_id, "COMPLETE", "IRRELEVANT", None, 1, None, 1, 2)
    )
    workflow = UnderstandingWorkflow(use_case, inbox, checkpoints)
    result = await workflow.run_understanding(item_id)
    assert result.status == "COMPLETE"
    assert use_case.calls == 0 and inbox.transitions == [] and checkpoints.writes == []
