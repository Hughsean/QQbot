"""Understanding handler that schedules durable Agent processing for mail."""

from typing import Protocol
from uuid import UUID

from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.workflow.contracts import WorkflowUseCase


class AgentRunScheduler(Protocol):
    async def schedule(self, inbox_item_id: UUID) -> None: ...


class UnderstandingAgentJobHandler:
    def __init__(self, workflow: WorkflowUseCase, scheduler: AgentRunScheduler) -> None:
        self._workflow = workflow
        self._scheduler = scheduler

    async def __call__(self, job: JobLease) -> None:
        raw_id = job.payload.get("inbox_item_id")
        if not isinstance(raw_id, str):
            raise ValueError("understanding job inbox_item_id is required")
        item_id = UUID(raw_id)
        await self._workflow.run_understanding(item_id)
        await self._scheduler.schedule(item_id)
