"""Worker adapters for versioned source asset jobs."""

from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.inbox.application.asset_fetch import SourceAssetFetchService
from qq_time_agent.modules.inbox.application.asset_parse import SourceAssetParseService


class SourceAssetFetchJobHandler:
    def __init__(self, service: SourceAssetFetchService, clock: Clock) -> None:
        self._service = service
        self._clock = clock

    async def __call__(self, job: JobLease) -> None:
        asset_id, version = _payload(job)
        await self._service.fetch(asset_id, version, self._clock.now())


class SourceAssetParseJobHandler:
    def __init__(self, service: SourceAssetParseService, clock: Clock) -> None:
        self._service = service
        self._clock = clock

    async def __call__(self, job: JobLease) -> None:
        asset_id, version = _payload(job)
        await self._service.parse(asset_id, version, self._clock.now())


def _payload(job: JobLease) -> tuple[UUID, int]:
    asset_id = job.payload.get("asset_id")
    version = job.payload.get("version")
    if not isinstance(asset_id, str) or not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("invalid source asset job payload")
    try:
        return UUID(asset_id), version
    except ValueError as exc:
        raise ValueError("invalid source asset id") from exc
