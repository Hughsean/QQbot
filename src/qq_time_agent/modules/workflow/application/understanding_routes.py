"""Pure routing policies for the bounded Understanding graph."""

from typing import Literal

from qq_time_agent.modules.understanding.contracts import CandidateKind
from qq_time_agent.modules.workflow.application.understanding_state import UnderstandingState

StartRoute = Literal["classify", "extract", "persist", "apply", "done"]
ClassificationRoute = Literal["extract", "persist"]
ExtractionRoute = Literal["validate", "persist"]


def start_route(state: UnderstandingState) -> StartRoute:
    if state["phase"] == "COMPLETE":
        return "done"
    if state["phase"] == "DECIDED":
        return "apply"
    if state["phase"] == "CLASSIFIED":
        return classification_route(state)
    return "classify"


def classification_route(state: UnderstandingState) -> ClassificationRoute:
    raw_kind = state["result_kind"]
    requires_extraction = (
        raw_kind in {CandidateKind.EVENT.value, CandidateKind.TASK.value}
        and state["candidate_id"] is None
        and state["review_reason"] is None
    )
    return "extract" if requires_extraction else "persist"


def extraction_route(state: UnderstandingState) -> ExtractionRoute:
    return "validate" if state["candidate_draft"] is not None else "persist"
