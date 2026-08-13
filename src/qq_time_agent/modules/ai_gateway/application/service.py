"""Bounded model gateway recording only non-content metadata."""

import asyncio
from datetime import datetime
from uuid import uuid4

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.ai_gateway.application.ports import (
    InvocationMetadata,
    InvocationRepository,
)
from qq_time_agent.modules.ai_gateway.contracts import (
    ModelFailure,
    StructuredModelPort,
    StructuredRequest,
    StructuredResponse,
)


class AIGatewayService:
    def __init__(
        self,
        provider: StructuredModelPort,
        repository: InvocationRepository,
        clock: Clock,
        max_concurrency: int,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("AI concurrency must be positive")
        self._provider = provider
        self._repository = repository
        self._clock = clock
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def invoke(self, request: StructuredRequest) -> StructuredResponse:
        started = self._clock.now()
        try:
            async with self._semaphore:
                response = await self._provider.invoke(request)
        except ModelFailure as exc:
            await self._record(request, started, None, exc.failure_class)
            raise
        except Exception as exc:
            await self._record(request, started, None, "UnexpectedProvider")
            raise ModelFailure("UnexpectedProvider") from exc
        await self._record(request, started, response, None)
        return response

    async def _record(
        self,
        request: StructuredRequest,
        started: datetime,
        response: StructuredResponse | None,
        failure_class: str | None,
    ) -> None:
        completed = self._clock.now()
        await self._repository.add(
            InvocationMetadata(
                uuid4(),
                request.use_case,
                request.prompt_version,
                request.route.value,
                None if response is None else response.model,
                "FAILED" if failure_class else "SUCCEEDED",
                failure_class,
                0 if response is None else response.input_tokens,
                0 if response is None else response.output_tokens,
                started,
                completed,
                max(0, int((completed - started).total_seconds() * 1000)),
            )
        )
