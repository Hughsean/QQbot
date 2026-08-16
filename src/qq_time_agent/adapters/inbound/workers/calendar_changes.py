"""Worker adapter for deterministic calendar change candidates."""

from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.modules.normalization.contracts import AssetNormalizationQueryPort
from qq_time_agent.modules.understanding.application.calendar_ingestion import (
    CalendarChangeIngestionService,
)


class CalendarChangeIngestJobHandler:
    def __init__(
        self,
        assets: AssetNormalizationQueryPort,
        service: CalendarChangeIngestionService,
        clock: Clock,
    ) -> None:
        self._assets = assets
        self._service = service
        self._clock = clock

    async def __call__(self, job: JobLease) -> None:
        asset_id = _asset_id(job)
        asset = await self._assets.get_asset(asset_id)
        if asset is None or asset.calendar is None:
            return
        await self._service.ingest(
            asset.asset_id,
            asset.inbox_item_id,
            asset.source_ref,
            asset.calendar,
            self._clock.now(),
        )


def _asset_id(job: JobLease) -> UUID:
    value = job.payload.get("asset_id")
    version = job.payload.get("version")
    if not isinstance(value, str) or not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("invalid calendar change job payload")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError("invalid source asset id") from exc
