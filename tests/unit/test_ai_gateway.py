from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from qq_time_agent.modules.ai_gateway.application.ports import InvocationMetadata
from qq_time_agent.modules.ai_gateway.application.service import AIGatewayService
from qq_time_agent.modules.ai_gateway.contracts import (
    ModelFailure,
    ModelRoute,
    StructuredRequest,
    StructuredResponse,
    TokenBudget,
)


@dataclass
class Clock:
    values: list[datetime]

    def now(self) -> datetime:
        return self.values.pop(0)


@dataclass
class Provider:
    result: StructuredResponse | Exception

    async def invoke(self, request: StructuredRequest) -> StructuredResponse:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@dataclass
class Repository:
    values: list[InvocationMetadata] = field(default_factory=list)

    async def add(self, metadata: InvocationMetadata) -> None:
        self.values.append(metadata)


def _request() -> StructuredRequest:
    return StructuredRequest(
        "understanding.classify",
        "v1",
        ModelRoute.FAST,
        "Return json",
        "private body must never be persisted",
        "user-safe",
    )


def test_structured_request_validates_provider_neutral_token_budget() -> None:
    request = StructuredRequest(
        "agent.loop",
        "v1",
        ModelRoute.FAST,
        "Return JSON",
        "data",
        "user-safe",
        100,
        TokenBudget(1_000, 50),
    )
    assert request.token_budget == TokenBudget(1_000, 50)
    with pytest.raises(ValueError, match="output reservation"):
        StructuredRequest(
            "agent.loop",
            "v1",
            ModelRoute.FAST,
            "Return JSON",
            "data",
            "user-safe",
            950,
            TokenBudget(1_000, 50),
        )


@pytest.mark.asyncio
async def test_gateway_records_non_content_success_metadata() -> None:
    start = datetime(2026, 8, 13, tzinfo=UTC)
    repository = Repository()
    gateway = AIGatewayService(
        Provider(StructuredResponse({"kind": "TASK"}, "model", 10, 4)),
        repository,
        Clock([start, start + timedelta(milliseconds=125)]),
        2,
    )
    await gateway.invoke(_request())
    value = repository.values[0]
    assert (value.status, value.input_tokens, value.output_tokens, value.latency_ms) == (
        "SUCCEEDED",
        10,
        4,
        125,
    )
    assert "private body" not in repr(value)


@pytest.mark.asyncio
async def test_gateway_records_classified_failure_without_payload() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    repository = Repository()
    gateway = AIGatewayService(
        Provider(ModelFailure("TimeoutOrNetwork")), repository, Clock([now, now]), 1
    )
    with pytest.raises(ModelFailure, match="TimeoutOrNetwork"):
        await gateway.invoke(_request())
    assert repository.values[0].failure_class == "TimeoutOrNetwork"
    assert repository.values[0].model is None


def test_gateway_rejects_non_positive_concurrency() -> None:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    with pytest.raises(ValueError, match="positive"):
        AIGatewayService(Provider(ModelFailure("x")), Repository(), Clock([now]), 0)
