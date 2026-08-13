"""Thin worker handler for constrained Understanding workflow."""

from uuid import UUID

from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.workflow.contracts import WorkflowUseCase


class UnderstandingJobHandler:
    def __init__(self, workflow: WorkflowUseCase) -> None:
        self._workflow = workflow

    async def __call__(self, job: JobLease) -> None:
        raw_id = job.payload.get("inbox_item_id")
        if not isinstance(raw_id, str):
            raise ValueError("understanding job inbox_item_id is required")
        await self._workflow.run_understanding(UUID(raw_id))
