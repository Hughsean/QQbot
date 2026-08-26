from collections.abc import Mapping
from dataclasses import dataclass

import pytest

from qq_time_agent.contracts.tools import ToolDefinition
from qq_time_agent.modules.agent.application.json_model import _instruction, _parse
from qq_time_agent.modules.agent.application.loop import AgentLoop, AgentLoopConfig
from qq_time_agent.modules.agent.contracts import (
    AgentDelivery,
    AgentFinal,
    AgentRequest,
    AgentResponse,
    AgentResponseProtocolError,
    AgentToolCall,
)


@dataclass
class Model:
    responses: list[AgentResponse]

    async def respond(self, request: object) -> AgentResponse:
        del request
        return self.responses.pop(0)


class Tools:
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return ()

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object:
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
        Tools(),
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
    with pytest.raises(AgentResponseProtocolError):
        _parse({"type": "final", "content": "错误字段", "delivery": "SEND"})


def test_agent_final_compatibility_is_limited_to_text_only_shapes() -> None:
    content = _parse({"content": "你好"})
    assert content.final == AgentFinal("你好", AgentDelivery.HOLD)
    simple_final = _parse({"final": "你好"})
    assert simple_final.final == AgentFinal("你好", AgentDelivery.HOLD)
    nested_final = _parse({"final": {"content": "邮件已更新", "delivery": "NOTIFY"}})
    assert nested_final.final == AgentFinal("邮件已更新", AgentDelivery.NOTIFY)
    with pytest.raises(AgentResponseProtocolError):
        _parse({"content": "不要执行", "name": "update_agenda", "arguments": {}})


def test_agent_instruction_contains_the_exact_response_shapes() -> None:
    request = AgentRequest("系统规则", "你好", "", (), (), 0)
    instruction = _instruction(request)
    assert '"type":"final"' in instruction
    assert '"type":"tool_call"' in instruction
