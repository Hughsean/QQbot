"""Structured-model adapter for the provider-neutral Agent loop."""

import json
import logging
from collections.abc import Mapping
from typing import NoReturn

from qq_time_agent.modules.agent.contracts import (
    AgentDelivery,
    AgentFinal,
    AgentModelPort,
    AgentRequest,
    AgentResponse,
    AgentResponseProtocolError,
    AgentToolCall,
)
from qq_time_agent.modules.ai_gateway.contracts import (
    ModelRoute,
    StructuredModelPort,
    StructuredRequest,
)

LOGGER = logging.getLogger(__name__)


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
        "只返回一个 JSON 对象, 不得使用 Markdown, 代码块或额外文字. 你是一个有界 Agent, "
        "输出只能严格是以下两种形状之一:\n"
        '{"type":"final","content":"给用户的答复","delivery":"HOLD"}\n'
        '{"type":"tool_call","call_id":"本回合唯一标识","name":"工具名","arguments":{}}\n'
        "不得省略 type, 不得使用 final、answer、result 等替代字段. "
        "tool_call.arguments 必须符合对应 input_schema. 不得伪造工具结果.\n"
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
    if kind in {"final", "answer", "final_answer"}:
        return _final_response(output.get("content"), output.get("delivery"), output)
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
            _raise_invalid(output, "tool_call_fields")
        return AgentResponse(tool_call=AgentToolCall(call_id, name, arguments))
    if kind is None and set(output).issubset({"content", "delivery"}):
        return _final_response(output.get("content"), output.get("delivery"), output)
    if kind is None and set(output).issubset({"final", "delivery"}):
        final = output.get("final")
        if isinstance(final, str):
            return _final_response(final, output.get("delivery"), output)
        if isinstance(final, Mapping) and set(final).issubset({"content", "delivery"}):
            return _final_response(
                final.get("content"), final.get("delivery", output.get("delivery")), output
            )
    _raise_invalid(output, "response_type")


def _final_response(
    content: object, delivery: object, output: Mapping[str, object]
) -> AgentResponse:
    if not isinstance(content, str) or not content.strip():
        _raise_invalid(output, "final_content")
    if delivery is None:
        return AgentResponse(final=AgentFinal(content.strip(), AgentDelivery.HOLD))
    if not isinstance(delivery, str):
        _raise_invalid(output, "final_delivery")
    try:
        return AgentResponse(final=AgentFinal(content.strip(), AgentDelivery(delivery)))
    except ValueError:
        _raise_invalid(output, "final_delivery")


def _raise_invalid(output: Mapping[str, object], reason: str) -> NoReturn:
    response_type = output.get("type")
    LOGGER.warning(
        "Agent 模型响应协议无效: 已拒绝未受支持的结构",
        extra={
            "role": "agent",
            "status": "invalid_response_protocol",
            "reason": reason,
            "output_keys": ",".join(sorted(str(key) for key in output)),
            "response_type": type(response_type).__name__,
        },
    )
    raise AgentResponseProtocolError("Agent response protocol is invalid")
