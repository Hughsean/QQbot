"""Bounded database job runner with explicit handler registration."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease, JobQueue

LOGGER = logging.getLogger(__name__)


type JobHandler = Callable[[JobLease], Awaitable[None]]


class RetryableJobError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


class JobRunner:
    def __init__(
        self,
        queue: JobQueue,
        handlers: Mapping[str, JobHandler],
        clock: Clock,
        worker_id: str,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        before_poll: Callable[[], Awaitable[None]] | None = None,
        before_start: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._queue = queue
        self._handlers = handlers
        self._clock = clock
        self._worker_id = worker_id
        self._sleep = sleep
        self._before_poll = before_poll
        self._before_start = before_start

    async def run_once(self, limit: int = 20) -> int:
        if self._before_poll is not None:
            await self._before_poll()
        now = self._clock.now()
        jobs = await self._queue.lease_due(now, self._worker_id, limit, timedelta(minutes=2))
        for job in jobs:
            await self._handle(job)
        if jobs:
            LOGGER.info("job batch processed", extra={"count": len(jobs)})
        return len(jobs)

    async def run_forever(self, idle_seconds: float = 1.0) -> None:
        if self._before_start is not None:
            await self._before_start()
        while True:
            processed = await self.run_once()
            if processed == 0:
                await self._sleep(idle_seconds)

    async def _handle(self, job: JobLease) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            await self._queue.fail(job, self._clock.now(), "PermanentProvider", None)
            LOGGER.warning(
                "job kind is not registered",
                extra={"job_id": job.job_id, "kind": job.kind, "attempt": job.attempt_count},
            )
            return
        try:
            await handler(job)
        except RetryableJobError as exc:
            retry_at = _next_retry(self._clock.now(), job.attempt_count)
            await self._queue.fail(job, self._clock.now(), exc.failure_class, retry_at)
            LOGGER.warning(
                "job failed retryably",
                extra={
                    "job_id": job.job_id,
                    "kind": job.kind,
                    "attempt": job.attempt_count,
                    "failure_class": exc.failure_class,
                },
            )
        except Exception:
            await self._queue.fail(job, self._clock.now(), "PermanentProvider", None)
            LOGGER.exception(
                "job failed permanently",
                extra={
                    "job_id": job.job_id,
                    "kind": job.kind,
                    "attempt": job.attempt_count,
                    "failure_class": "PermanentProvider",
                },
            )
        else:
            await self._queue.complete(job, self._clock.now())


def _next_retry(now: datetime, attempt_count: int) -> datetime:
    seconds = min(300, 2 ** min(attempt_count, 8))
    return now + timedelta(seconds=seconds)
