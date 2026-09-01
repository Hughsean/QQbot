from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.contracts.tools import ToolDefinition
from qq_time_agent.modules.agent.application.loop import AgentLoop
from qq_time_agent.modules.agent.application.run_service import AgentRunService
from qq_time_agent.modules.agent.contracts import (
    AgentFinal,
    AgentResponse,
    AgentRun,
    AgentRunStatus,
    AgentToolCall,
    ToolObservation,
)


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 27, tzinfo=UTC)


@dataclass
class Model:
    responses: list[AgentResponse | Exception]

    async def respond(self, request: object) -> AgentResponse:
        del request
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


@dataclass
class Tools:
    calls: int = 0

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return (ToolDefinition("update_agenda", "test", {"type": "object", "properties": {}}),)

    async def call(
        self,
        owner_id: str,
        name: str,
        arguments: dict[str, object],
        context: object,
    ) -> object:
        del context
        assert owner_id == "owner" and name == "update_agenda" and arguments == {}
        self.calls += 1
        return {"status": "SUCCEEDED"}


@dataclass
class Repository:
    run: AgentRun

    async def get(self, run_id: UUID) -> AgentRun | None:
        return self.run if run_id == self.run.run_id else None

    async def save(self, run: AgentRun, expected_version: int) -> None:
        assert expected_version == self.run.version
        run.version += 1
        self.run = run

    async def checkpoint_tool_call(
        self, run_id: UUID, observation: ToolObservation, now: datetime
    ) -> None:
        assert run_id == self.run.run_id
        self.run.observations.append(
            {
                "call_id": observation.call_id,
                "name": observation.name,
                "output": str(observation.output),
                "is_error": observation.is_error,
                "arguments_hash": observation.arguments_hash,
            }
        )
        self.run.step = len(self.run.observations)
        self.run.updated_at = now
        self.run.version += 1


@pytest.mark.asyncio
async def test_recovery_reuses_checkpointed_tool_observation_without_repeating_call() -> None:
    run = AgentRun(uuid4(), uuid4(), "owner", "QQ_DIRECT", AgentRunStatus.PENDING, 0)
    repository = Repository(run)
    tools = Tools()
    model = Model(
        [
            AgentResponse(tool_call=AgentToolCall("call-1", "update_agenda", {})),
            RuntimeError("interrupted"),
            AgentResponse(tool_call=AgentToolCall("call-1", "update_agenda", {})),
            AgentResponse(final=AgentFinal("已更新")),
        ]
    )
    service = AgentRunService(repository, AgentLoop(model, tools), Clock())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="interrupted"):
        await service.execute(run.run_id, "更新日程")
    assert tools.calls == 1, repository.run.observations
    assert len(repository.run.observations) == 1
    result = await service.execute(run.run_id, "更新日程")

    assert result.content == "已更新"
    assert tools.calls == 1
    assert len(repository.run.observations) == 1
