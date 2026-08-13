"""DeepSeek JSON Output adapter with bounded timeout and retry."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping

import httpx

from qq_time_agent.bootstrap.config_models import DeepSeekConfig
from qq_time_agent.modules.ai_gateway.contracts import (
    ModelFailure,
    ModelRoute,
    StructuredRequest,
    StructuredResponse,
)

RETRYABLE = {408, 409, 429, 500, 502, 503, 504}


class DeepSeekStructuredAdapter:
    def __init__(
        self,
        config: DeepSeekConfig,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(base_url=config.base_url)
        self._owns_client = client is None
        self._sleep = sleep

    async def invoke(self, request: StructuredRequest) -> StructuredResponse:
        model, timeout = self._route(request.route)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system_instruction},
                {"role": "user", "content": request.external_data},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": request.max_output_tokens,
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "user_id": request.user_alias,
        }
        response = await self._post(payload, timeout)
        try:
            body = response.json()
            choice = _mapping(_sequence(body, "choices")[0])
            if choice.get("finish_reason") != "stop":
                raise ValueError("model output did not finish normally")
            content = _mapping(choice, "message").get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("model returned empty JSON content")
            output = json.loads(content)
            if not isinstance(output, dict):
                raise TypeError("model JSON output must be an object")
            usage = _mapping(body, "usage")
            return StructuredResponse(
                output,
                _string(body, "model"),
                _integer(usage, "prompt_tokens"),
                _integer(usage, "completion_tokens"),
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ModelFailure("InvalidOutput") from exc

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _route(self, route: ModelRoute) -> tuple[str, float]:
        if route is ModelRoute.REASONING:
            return self._config.reasoning_model, self._config.reasoning_timeout_seconds
        return self._config.fast_model, self._config.fast_timeout_seconds

    async def _post(self, payload: dict[str, object], timeout: float) -> httpx.Response:
        attempts = self._config.max_retries + 1
        url = self._config.base_url.rstrip("/") + "/chat/completions"
        for attempt in range(attempts):
            try:
                response = await self._client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": ("Bearer " + self._config.api_key.get_secret_value())
                    },
                    timeout=timeout,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt + 1 == attempts:
                    raise ModelFailure("TimeoutOrNetwork") from exc
                await self._sleep(2.0**attempt)
                continue
            if 200 <= response.status_code < 300:
                return response
            failure = _failure(response.status_code)
            if response.status_code in RETRYABLE and attempt + 1 < attempts:
                await self._sleep(min(30.0, 2.0**attempt))
                continue
            raise ModelFailure(failure)
        raise AssertionError("unreachable")


def _failure(status: int) -> str:
    if status in {401, 402}:
        return "AuthenticationOrBalance"
    if status == 403:
        return "Authorization"
    if status == 429:
        return "RateLimit"
    if status >= 500:
        return "ProviderUnavailable"
    return "InvalidRequest"


def _mapping(value: object, key: str | None = None) -> Mapping[str, object]:
    result = value if key is None else _mapping(value).get(key)
    if not isinstance(result, dict):
        raise TypeError
    return result


def _sequence(value: object, key: str) -> list[object]:
    result = _mapping(value).get(key)
    if not isinstance(result, list):
        raise TypeError
    return result


def _string(value: object, key: str) -> str:
    result = _mapping(value).get(key)
    if not isinstance(result, str):
        raise TypeError
    return result


def _integer(value: object, key: str) -> int:
    result = _mapping(value).get(key)
    if not isinstance(result, int):
        raise TypeError
    return result
