"""Workflow result exposes control outcome and business identifiers only."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    inbox_item_id: UUID
    status: str
    candidate_id: UUID | None
    review_reason: str | None
    model_calls: int


class WorkflowUseCase(Protocol):
    async def run_understanding(self, inbox_item_id: UUID) -> WorkflowResult: ...
