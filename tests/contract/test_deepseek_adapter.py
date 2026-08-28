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
    TokenBudget,
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


def _request(
    route: ModelRoute = ModelRoute.FAST, token_budget: TokenBudget | None = None
) -> StructuredRequest:
    return StructuredRequest(
        "test",
        "v1",
        route,
        "Return json only",
        "<EXTERNAL_DATA>x</EXTERNAL_DATA>",
        "user-safe",
        100,
        token_budget,
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
async def test_deepseek_preflights_exact_serialized_request_before_network() -> None:
    sent: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.content)
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = DeepSeekStructuredAdapter(_config(), client)
    with pytest.raises(ModelFailure, match="ContextBudgetExceeded"):
        await adapter.invoke(_request(token_budget=TokenBudget(150, 1)))
    assert sent == []


@pytest.mark.asyncio
async def test_deepseek_sends_the_same_compact_utf8_bytes_used_by_preflight() -> None:
    captured: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.content)
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    request = StructuredRequest(
        "test",
        "v1",
        ModelRoute.FAST,
        "只返回 JSON",
        "<EXTERNAL_DATA>明天</EXTERNAL_DATA>",
        "user-safe",
        100,
        TokenBudget(1_000, 10),
    )
    adapter = DeepSeekStructuredAdapter(
        _config(), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await adapter.invoke(request)
    assert len(captured) == 1
    decoded = captured[0].decode("utf-8")
    assert "明天" in decoded
    assert "\\u660e" not in decoded
    assert decoded == json.dumps(json.loads(decoded), ensure_ascii=False, separators=(",", ":"))


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
