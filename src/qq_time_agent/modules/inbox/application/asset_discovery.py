"""Idempotent mail attachment discovery and durable job recovery."""

from datetime import datetime, timedelta
from pathlib import PurePath
from uuid import UUID

from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.contracts.source import SourceAssetDescriptor
from qq_time_agent.modules.inbox.application.asset_ports import SourceAssetRepository
from qq_time_agent.modules.inbox.domain.assets import AssetFetchStatus, AssetKind, SourceAsset


class MailAssetDiscoveryService:
    def __init__(
        self,
        repository: SourceAssetRepository,
        jobs: JobQueue,
        raw_retention_hours: int,
    ) -> None:
        if raw_retention_hours < 1 or raw_retention_hours > 24:
            raise ValueError("raw asset retention must be between 1 and 24 hours")
        self._repository = repository
        self._jobs = jobs
        self._retention = timedelta(hours=raw_retention_hours)

    async def discover(
        self,
        inbox_item_id: UUID,
        attachments: tuple[SourceAssetDescriptor, ...],
        now: datetime,
    ) -> tuple[UUID, ...]:
        asset_ids: list[UUID] = []
        for descriptor in attachments:
            asset = SourceAsset.discover(
                inbox_item_id,
                descriptor.provider_asset_id,
                descriptor.provider_locator,
                _asset_kind(descriptor),
                descriptor.content_type,
                now,
                now + self._retention,
                filename=descriptor.filename,
                declared_size=descriptor.declared_size,
                transfer_encoding=descriptor.transfer_encoding,
            )
            persisted = await self._repository.add_or_get(asset)
            if persisted.fetch_status is AssetFetchStatus.DISCOVERED:
                await self._enqueue(persisted, now)
            asset_ids.append(persisted.asset_id)
        return tuple(asset_ids)

    async def recover_pending(self, now: datetime, limit: int = 100) -> int:
        pending = await self._repository.list_pending(limit)
        for asset in pending:
            await self._enqueue(asset, now)
        return len(pending)

    async def _enqueue(self, asset: SourceAsset, now: datetime) -> None:
        await self._jobs.enqueue(
            JobRequest(
                "source-asset-fetch",
                {"asset_id": str(asset.asset_id), "version": asset.version},
                f"source-asset-fetch:{asset.asset_id}:v{asset.version}",
                now,
            )
        )


def _asset_kind(descriptor: SourceAssetDescriptor) -> AssetKind:
    content_type = descriptor.content_type.partition(";")[0].strip().lower()
    suffix = PurePath(descriptor.filename or "").suffix.lower()
    if content_type == "application/pdf" or suffix == ".pdf":
        return AssetKind.PDF
    if content_type in {"text/calendar", "application/ics"} or suffix == ".ics":
        return AssetKind.ICS
    if content_type.startswith("image/"):
        return AssetKind.IMAGE
    if content_type.startswith("text/"):
        return AssetKind.TEXT
    return AssetKind.FILE
