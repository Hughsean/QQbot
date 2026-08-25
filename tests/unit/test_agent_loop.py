from dataclasses import dataclass

import pytest

from qq_time_agent.modules.agent.application.loop import AgentLoop, AgentLoopConfig
from qq_time_agent.modules.agent.contracts import (
    AgentFinal,
    AgentResponse,
    AgentToolCall,
)


@dataclass
class Model:
    responses: list[AgentResponse]

    async def respond(self, request: object) -> AgentResponse:
        del request
        return self.responses.pop(0)


class Tools:
    def definitions(self) -> tuple[object, ...]:
        return ()

    async def call(self, owner_id: str, name: str, arguments: dict[str, object]) -> object:
        assert owner_id == "owner" and name == "ping" and arguments == {}
        return {"ok": True}


@pytest.mark.asyncio
async def test_agent_loop_observes_tool_then_reports_final() -> None:
    loop = AgentLoop(
        Model(
            [
                AgentResponse(tool_call=AgentToolCall("c1", "ping", {})),
                AgentResponse(final=AgentFinal("已完成")),
            ]
        ),
        Tools(),  # type: ignore[arg-type]
    )
    result = await loop.run("owner", "处理一下")
    assert result.content == "已完成"


@pytest.mark.asyncio
async def test_agent_loop_rejects_non_owner_and_step_limit() -> None:
    with pytest.raises(ValueError, match="max steps"):
        AgentLoop(Model([]), Tools(), config=AgentLoopConfig(max_steps=0))
