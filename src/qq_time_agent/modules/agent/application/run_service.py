"""Durable execution boundary for owner and mail Agent runs."""

import hashlib
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agent.application.loop import AgentLoop
from qq_time_agent.modules.agent.contracts import (
    AgentFinal,
    AgentRun,
    AgentRunRepository,
    AgentRunStatus,
    ToolObservation,
)


class AgentRunService:
    def __init__(self, repository: AgentRunRepository, loop: AgentLoop, clock: Clock) -> None:
        self._repository = repository
        self._loop = loop
        self._clock = clock

    async def ensure_run(self, inbox_item_id: UUID, user_id: str, source_type: str) -> AgentRun:
        return await self._repository.get_or_create(
            inbox_item_id, user_id, source_type, self._clock.now()
        )

    async def execute(self, run_id: UUID, message: str, context: str = "") -> AgentFinal:
        run = await self._repository.get(run_id)
        if run is None:
            raise LookupError("AgentRun does not exist")
        if run.status is AgentRunStatus.COMPLETED and run.final_content is not None:
            return AgentFinal(run.final_content)
        expected_version = run.version
        run.status = AgentRunStatus.RUNNING
        run.updated_at = self._clock.now()
        await self._repository.save(run, expected_version)
        try:

            async def record(observation: ToolObservation) -> None:
                await self._repository.record_tool_call(
                    run_id,
                    observation.call_id,
                    observation.name,
                    hashlib.sha256(observation.call_id.encode()).hexdigest(),
                    {
                        "is_error": observation.is_error,
                        "output_type": type(observation.output).__name__,
                    },
                    self._clock.now(),
                )

            result = await self._loop.run(run.user_id, message, context, on_tool_call=record)
        except Exception as exc:
            current = await self._repository.get(run_id)
            if current is not None:
                current.status = AgentRunStatus.FAILED
                current.failure_class = type(exc).__name__
                current.updated_at = self._clock.now()
                await self._repository.save(current, current.version)
            raise
        current = await self._repository.get(run_id)
        if current is None:
            raise RuntimeError("AgentRun disappeared during execution")
        current.status = AgentRunStatus.COMPLETED
        current.final_content = result.content[:12000]
        current.updated_at = self._clock.now()
        await self._repository.save(current, current.version)
        return result
