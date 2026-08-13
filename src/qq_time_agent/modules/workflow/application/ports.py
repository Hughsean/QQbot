"""Workflow-owned durable checkpoint port."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkflowCheckpoint:
    inbox_item_id: UUID
    phase: str
    result_kind: str | None
    candidate_id: UUID | None
    confidence: float | None
    review_reason: str | None
    model_calls: int
    version: int
    source_ref: str | None = None


class WorkflowCheckpointRepository(Protocol):
    async def get(self, inbox_item_id: UUID) -> WorkflowCheckpoint | None: ...

    async def save(self, checkpoint: WorkflowCheckpoint) -> None: ...
