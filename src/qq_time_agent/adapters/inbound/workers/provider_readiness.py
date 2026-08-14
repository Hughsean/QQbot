"""Startup readiness gates for providers required before job leasing."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from qq_time_agent.modules.embeddings.contracts import EmbeddingPort

LOGGER = logging.getLogger(__name__)


class EmbeddingStartupGate:
    def __init__(
        self,
        provider: EmbeddingPort,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_seconds: float = 5.0,
        log_every: int = 6,
    ) -> None:
        if retry_seconds <= 0 or log_every < 1:
            raise ValueError("readiness retry settings must be positive")
        self._provider = provider
        self._sleep = sleep
        self._retry_seconds = retry_seconds
        self._log_every = log_every

    async def wait(self) -> None:
        attempt = 0
        while True:
            attempt += 1
            health = await self._provider.health()
            if health.available:
                LOGGER.info("embedding provider ready", extra={"attempt": attempt})
                return
            if attempt == 1 or attempt % self._log_every == 0:
                LOGGER.warning(
                    "waiting for embedding provider",
                    extra={"attempt": attempt, "failure_class": health.failure_class},
                )
            await self._sleep(self._retry_seconds)
