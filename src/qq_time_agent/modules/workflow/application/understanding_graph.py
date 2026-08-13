"""Bounded LangGraph orchestration with ID-only durable state."""

from typing import Literal, TypedDict, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from qq_time_agent.modules.inbox.contracts import InboxProcessingPort, InboxSourcePort
from qq_time_agent.modules.understanding.contracts import (
    CandidateKind,
    UnderstandingUseCase,
)
from qq_time_agent.modules.workflow.application.ports import (
    WorkflowCheckpoint,
    WorkflowCheckpointRepository,
)
from qq_time_agent.modules.workflow.contracts import WorkflowResult


class UnderstandingState(TypedDict):
    inbox_item_id: str
    phase: str
    result_kind: str | None
    candidate_id: str | None
    confidence: float | None
    review_reason: str | None
    model_calls: int
    version: int


class UnderstandingWorkflow:
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
        self._graph = self._build_graph()

    async def run_understanding(self, inbox_item_id: UUID) -> WorkflowResult:
        checkpoint = await self._checkpoints.get(inbox_item_id)
        state = _state(checkpoint or _initial(inbox_item_id))
        result = await self._graph.ainvoke(state, {"recursion_limit": 8})
        final = cast("UnderstandingState", result)
        return WorkflowResult(
            inbox_item_id,
            final["phase"],
            _optional_uuid(final["candidate_id"]),
            final["review_reason"],
            final["model_calls"],
        )

    def _build_graph(
        self,
    ) -> CompiledStateGraph[UnderstandingState, None, UnderstandingState, UnderstandingState]:
        graph = StateGraph(UnderstandingState)
        graph.add_node("understand", self._understand)
        graph.add_node("apply_disposition", self._apply_disposition)
        graph.add_conditional_edges(
            START,
            _start_route,
            {"understand": "understand", "apply": "apply_disposition", "done": END},
        )
        graph.add_edge("understand", "apply_disposition")
        graph.add_edge("apply_disposition", END)
        return graph.compile()

    async def _understand(self, state: UnderstandingState) -> UnderstandingState:
        inbox_item_id = UUID(state["inbox_item_id"])
        result = await self._understanding.understand(inbox_item_id)
        source_ref = await self._source_ref(inbox_item_id)
        checkpoint = WorkflowCheckpoint(
            inbox_item_id,
            "DECIDED",
            result.kind.value,
            result.candidate_id,
            result.confidence,
            result.review_reason,
            result.model_calls,
            state["version"] + 1,
            source_ref,
        )
        await self._checkpoints.save(checkpoint)
        return _state(checkpoint)

    async def _apply_disposition(self, state: UnderstandingState) -> UnderstandingState:
        inbox_item_id = UUID(state["inbox_item_id"])
        raw_kind = state["result_kind"]
        if raw_kind is None:
            raise RuntimeError("decided workflow is missing result kind")
        kind = CandidateKind(raw_kind)
        if kind in {CandidateKind.EVENT, CandidateKind.TASK}:
            await self._inbox.mark_understood(inbox_item_id)
        elif kind is CandidateKind.IRRELEVANT:
            await self._inbox.mark_ignored(inbox_item_id)
        else:
            await self._inbox.mark_needs_review(inbox_item_id)
        checkpoint = WorkflowCheckpoint(
            inbox_item_id,
            "COMPLETE",
            state["result_kind"],
            _optional_uuid(state["candidate_id"]),
            state["confidence"],
            state["review_reason"],
            state["model_calls"],
            state["version"] + 1,
            await self._source_ref(inbox_item_id),
        )
        await self._checkpoints.save(checkpoint)
        return _state(checkpoint)

    async def _source_ref(self, inbox_item_id: UUID) -> str | None:
        if self._sources is None:
            return None
        source = await self._sources.get_source(inbox_item_id)
        return None if source is None else source.source_ref


def _start_route(state: UnderstandingState) -> Literal["understand", "apply", "done"]:
    if state["phase"] == "COMPLETE":
        return "done"
    if state["phase"] == "DECIDED":
        return "apply"
    return "understand"


def _initial(inbox_item_id: UUID) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(inbox_item_id, "START", None, None, None, None, 0, 0)


def _state(value: WorkflowCheckpoint) -> UnderstandingState:
    return UnderstandingState(
        inbox_item_id=str(value.inbox_item_id),
        phase=value.phase,
        result_kind=value.result_kind,
        candidate_id=None if value.candidate_id is None else str(value.candidate_id),
        confidence=value.confidence,
        review_reason=value.review_reason,
        model_calls=value.model_calls,
        version=value.version,
    )


def _optional_uuid(value: str | None) -> UUID | None:
    return None if value is None else UUID(value)
