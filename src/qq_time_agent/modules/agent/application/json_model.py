"""Structured-model adapter for the provider-neutral Agent loop."""

import json
from collections.abc import Mapping

from qq_time_agent.modules.agent.contracts import (
    AgentDelivery,
    AgentFinal,
    AgentModelPort,
    AgentRequest,
    AgentResponse,
    AgentToolCall,
)
from qq_time_agent.modules.ai_gateway.contracts import (
    ModelRoute,
    StructuredModelPort,
    StructuredRequest,
)


class JsonAgentModel(AgentModelPort):
    def __init__(self, model: StructuredModelPort, user_alias: str = "owner") -> None:
        self._model = model
        self._user_alias = user_alias

    async def respond(self, request: AgentRequest) -> AgentResponse:
        response = await self._model.invoke(
            StructuredRequest(
                "agent.loop",
                "agent-loop-v1",
                ModelRoute.FAST,
                _instruction(request),
                _external_data(request),
                self._user_alias,
                1200,
            )
        )
        return _parse(response.output)


def _instruction(request: AgentRequest) -> str:
    tools = json.dumps(
        [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in request.tools
        ],
        ensure_ascii=False,
    )
    return (
        "只返回 JSON。你是一个有界 Agent。必须在 final 和 tool_call 中二选一。"
        "tool_call.arguments 必须符合对应 input_schema。不得伪造工具结果。\n"
        "final 必须包含 delivery, 取值只能是 HOLD 或 NOTIFY. 对用户直接消息, delivery 仅用于"
        "记录, 回复始终会立即送达当前会话. 对无人请求的邮件事件, 只有存在明确、可操作、"
        "与该邮件相关的结果时才用 NOTIFY; 需要更多信息、内容不完整、仅供记录或不确定时"
        "必须用 HOLD, 绝不能主动发送泛化追问.\n"
        + request.system_instruction
        + "\n可用工具:\n"
        + tools
    )


def _external_data(request: AgentRequest) -> str:
    value = {
        "user_message": request.user_message,
        "context_t2": request.context,
        "tool_observations": [
            {
                "call_id": item.call_id,
                "name": item.name,
                "output": item.output,
                "is_error": item.is_error,
            }
            for item in request.observations
        ],
        "step": request.step,
    }
    return json.dumps(value, ensure_ascii=False)


def _parse(output: Mapping[str, object]) -> AgentResponse:
    kind = output.get("type")
    if kind == "final":
        content = output.get("content")
        delivery = output.get("delivery")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Agent final content is required")
        if delivery is None:
            return AgentResponse(final=AgentFinal(content.strip(), AgentDelivery.HOLD))
        if not isinstance(delivery, str):
            raise ValueError("Agent final delivery is invalid")
        try:
            return AgentResponse(final=AgentFinal(content.strip(), AgentDelivery(delivery)))
        except ValueError as exc:
            raise ValueError("Agent final delivery is invalid") from exc
    if kind == "tool_call":
        call_id = output.get("call_id")
        name = output.get("name")
        arguments = output.get("arguments")
        if (
            not isinstance(call_id, str)
            or not call_id.strip()
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(arguments, dict)
        ):
            raise ValueError("Agent tool call is invalid")
        return AgentResponse(tool_call=AgentToolCall(call_id, name, arguments))
    raise ValueError("Agent response type is invalid")
