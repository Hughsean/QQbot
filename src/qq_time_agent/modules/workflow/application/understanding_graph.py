"""Bounded LangGraph orchestration with explicit recoverable stages."""

from typing import cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from qq_time_agent.modules.inbox.contracts import InboxProcessingPort, InboxSourcePort
from qq_time_agent.modules.understanding.contracts import UnderstandingUseCase
from qq_time_agent.modules.workflow.application.ports import WorkflowCheckpointRepository
from qq_time_agent.modules.workflow.application.understanding_nodes import UnderstandingNodes
from qq_time_agent.modules.workflow.application.understanding_routes import (
    classification_route,
    extraction_route,
    start_route,
)
from qq_time_agent.modules.workflow.application.understanding_state import (
    UnderstandingState,
    checkpoint_to_state,
    initial_checkpoint,
    optional_uuid,
)
from qq_time_agent.modules.workflow.contracts import WorkflowResult


class UnderstandingWorkflow:
    def __init__(
        self,
        understanding: UnderstandingUseCase,
        inbox: InboxProcessingPort,
        checkpoints: WorkflowCheckpointRepository,
        sources: InboxSourcePort | None = None,
    ) -> None:
        self._checkpoints = checkpoints
        self._nodes = UnderstandingNodes(understanding, inbox, checkpoints, sources)
        self._graph = self._build_graph()

    async def run_understanding(self, inbox_item_id: UUID) -> WorkflowResult:
        checkpoint = await self._checkpoints.get(inbox_item_id)
        state = checkpoint_to_state(checkpoint or initial_checkpoint(inbox_item_id))
        result = await self._graph.ainvoke(state, {"recursion_limit": 8})
        final = cast("UnderstandingState", result)
        return WorkflowResult(
            inbox_item_id,
            final["phase"],
            optional_uuid(final["candidate_id"]),
            final["review_reason"],
            final["model_calls"],
        )

    def _build_graph(
        self,
    ) -> CompiledStateGraph[UnderstandingState, None, UnderstandingState, UnderstandingState]:
        graph = StateGraph(UnderstandingState)
        graph.add_node("classify", self._nodes.classify)
        graph.add_node("extract_candidate", self._nodes.extract_candidate)
        graph.add_node("validate_candidate", self._nodes.validate_candidate)
        graph.add_node("persist_decision", self._nodes.persist_decision)
        graph.add_node("apply_disposition", self._nodes.apply_disposition)
        graph.add_conditional_edges(
            START,
            start_route,
            {
                "classify": "classify",
                "extract": "extract_candidate",
                "persist": "persist_decision",
                "apply": "apply_disposition",
                "done": END,
            },
        )
        graph.add_conditional_edges(
            "classify",
            classification_route,
            {"extract": "extract_candidate", "persist": "persist_decision"},
        )
        graph.add_conditional_edges(
            "extract_candidate",
            extraction_route,
            {"validate": "validate_candidate", "persist": "persist_decision"},
        )
        graph.add_edge("validate_candidate", "persist_decision")
        graph.add_edge("persist_decision", "apply_disposition")
        graph.add_edge("apply_disposition", END)
        return graph.compile()
