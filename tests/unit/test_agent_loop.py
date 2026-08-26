from dataclasses import dataclass

import pytest

from qq_time_agent.modules.agent.application.json_model import _parse
from qq_time_agent.modules.agent.application.loop import AgentLoop, AgentLoopConfig
from qq_time_agent.modules.agent.contracts import (
    AgentDelivery,
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
    assert result.delivery is AgentDelivery.HOLD


@pytest.mark.asyncio
async def test_agent_loop_rejects_non_owner_and_step_limit() -> None:
    with pytest.raises(ValueError, match="max steps"):
        AgentLoop(Model([]), Tools(), config=AgentLoopConfig(max_steps=0))


def test_agent_final_uses_safe_hold_default_for_missing_delivery_decision() -> None:
    response = _parse({"type": "final", "content": "发现明确的时间变更", "delivery": "NOTIFY"})
    assert response.final is not None and response.final.delivery is AgentDelivery.NOTIFY
    held = _parse({"type": "final", "content": "需要更多信息"})
    assert held.final is not None and held.final.delivery is AgentDelivery.HOLD
    with pytest.raises(ValueError, match="delivery"):
        _parse({"type": "final", "content": "错误字段", "delivery": "SEND"})
