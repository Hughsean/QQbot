"""Provider-neutral AgentMessage contract and structured-request projection."""

import json
from dataclasses import dataclass
from uuid import uuid4

import pytest

from qq_time_agent.modules.agent.application.json_model import JsonAgentModel
from qq_time_agent.modules.agent.contracts import AgentRequest
from qq_time_agent.modules.ai_gateway.contracts import (
    AgentMessage,
    AgentMessageRole,
    ModelRoute,
    StructuredRequest,
    StructuredResponse,
)


def test_agent_message_requires_content() -> None:
    with pytest.raises(ValueError, match="content is required"):
        AgentMessage(AgentMessageRole.USER, "   ")


def test_agent_message_labels_must_not_be_blank() -> None:
    with pytest.raises(ValueError, match="event type must be a label"):
        AgentMessage(AgentMessageRole.TOOL, "内容", event_id=uuid4(), event_type="  ")
    with pytest.raises(ValueError, match="delivery status must be a label"):
        AgentMessage(
            AgentMessageRole.TOOL, "内容", event_type="MAIL_NOTIFICATION", delivery_status=""
        )


def test_structured_request_carries_messages_and_defaults_empty() -> None:
    empty = StructuredRequest("use", "v1", ModelRoute.FAST, "instruction", "data", "owner")
    assert empty.messages == ()
    message = AgentMessage(
        AgentMessageRole.ASSISTANT, "答复", event_id=uuid4(), event_type="AGENT_REPLY"
    )
    request = StructuredRequest(
        "use", "v1", ModelRoute.FAST, "instruction", "data", "owner", messages=(message,)
    )
    assert request.messages == (message,)


@dataclass
class CapturingStructuredModel:
    request: StructuredRequest | None = None

    async def invoke(self, request: StructuredRequest) -> StructuredResponse:
        self.request = request
        return StructuredResponse(
            {"type": "final", "content": "答复", "delivery": "HOLD"}, "model", 1, 1
        )


@pytest.mark.asyncio
async def test_json_model_forwards_timeline_messages_to_structured_request() -> None:
    capturing = CapturingStructuredModel()
    model = JsonAgentModel(capturing)
    messages = (
        AgentMessage(AgentMessageRole.SYSTEM, "[conversation-summary 1-4]\n早期摘要"),
        AgentMessage(
            AgentMessageRole.USER, "用户消息", event_id=uuid4(), event_type="USER_MESSAGE"
        ),
        AgentMessage(
            AgentMessageRole.ASSISTANT, "答复", event_id=uuid4(), event_type="AGENT_REPLY"
        ),
        AgentMessage(
            AgentMessageRole.TOOL,
            "[external-event MAIL_NOTIFICATION DELIVERED]\n已向用户发送的邮件提醒快照",
            event_id=uuid4(),
            event_type="MAIL_NOTIFICATION",
            delivery_status="DELIVERED",
        ),
    )

    response = await model.respond(
        AgentRequest("系统", "你好", "上下文", (), (), 0, timeline_messages=messages)
    )

    assert response.final is not None and response.final.content == "答复"
    assert capturing.request is not None
    assert capturing.request.messages == messages


@pytest.mark.asyncio
async def test_json_model_external_data_ends_with_the_live_user_message() -> None:
    capturing = CapturingStructuredModel()
    model = JsonAgentModel(capturing)

    await model.respond(AgentRequest("系统", "你好", "上下文", (), (), 0))

    assert capturing.request is not None
    external = json.loads(capturing.request.external_data)
    keys = list(external)
    assert keys[-1] == "user_message"
    assert external["user_message"] == "你好"
    assert external["context_t2"] == "上下文"
    assert external["tool_observations"] == []
