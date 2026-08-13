import json

import httpx
import pytest
from pydantic import SecretStr

from qq_time_agent.adapters.outbound.ai.deepseek import DeepSeekStructuredAdapter
from qq_time_agent.bootstrap.config_models import DeepSeekConfig
from qq_time_agent.modules.ai_gateway.contracts import (
    ModelFailure,
    ModelRoute,
    StructuredRequest,
)


def _config() -> DeepSeekConfig:
    return DeepSeekConfig(
        SecretStr("synthetic-deepseek-key"),
        "https://api.deepseek.com",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        1,
        2,
        1,
        2,
    )


def _request(route: ModelRoute = ModelRoute.FAST) -> StructuredRequest:
    return StructuredRequest(
        "test",
        "v1",
        route,
        "Return json only",
        "<EXTERNAL_DATA>x</EXTERNAL_DATA>",
        "user-safe",
        100,
    )


@pytest.mark.asyncio
async def test_deepseek_json_contract_has_no_tools_and_maps_usage() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [{"finish_reason": "stop", "message": {"content": '{"kind":"TASK"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = DeepSeekStructuredAdapter(_config(), client)
    response = await adapter.invoke(_request())
    assert response.output == {"kind": "TASK"}
    assert (response.input_tokens, response.output_tokens) == (12, 4)
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["thinking"] == {"type": "disabled"}
    assert "tools" not in captured and "tool_choice" not in captured
    assert "api_key" not in json.dumps(captured)


@pytest.mark.asyncio
async def test_deepseek_retries_transient_and_rejects_invalid_output() -> None:
    calls = 0
    delays: list[float] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-pro",
                "choices": [{"finish_reason": "length", "message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    async def sleep(value: float) -> None:
        delays.append(value)

    adapter = DeepSeekStructuredAdapter(
        _config(), httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep
    )
    with pytest.raises(ModelFailure, match="InvalidOutput"):
        await adapter.invoke(_request(ModelRoute.REASONING))
    assert calls == 2 and delays == [1.0]


@pytest.mark.asyncio
async def test_deepseek_timeout_is_bounded_and_classified() -> None:
    calls = 0
    delays: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    async def sleep(value: float) -> None:
        delays.append(value)

    adapter = DeepSeekStructuredAdapter(
        _config(), httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep
    )
    with pytest.raises(ModelFailure, match="TimeoutOrNetwork"):
        await adapter.invoke(_request())
    assert calls == 2 and delays == [1.0]
