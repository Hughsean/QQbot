"""Restart-safe source asset parsing and normalized text persistence."""

from datetime import datetime
from uuid import UUID

from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.modules.inbox.application.asset_ports import (
    AssetBlobStore,
    SourceAssetRepository,
)
from qq_time_agent.modules.inbox.domain.assets import (
    AssetFetchStatus,
    AssetKind,
    AssetParseStatus,
    SourceAsset,
)
from qq_time_agent.modules.normalization.contracts import (
    AssetNormalizationPort,
    AssetParseError,
    AssetParserPort,
    NormalizableAssetKind,
)


class SourceAssetParseService:
    def __init__(
        self,
        repository: SourceAssetRepository,
        blobs: AssetBlobStore,
        parser: AssetParserPort,
        normalization: AssetNormalizationPort,
        jobs: JobQueue,
        owner_timezone: str,
    ) -> None:
        self._repository = repository
        self._blobs = blobs
        self._parser = parser
        self._normalization = normalization
        self._jobs = jobs
        self._owner_timezone = owner_timezone

    async def parse(self, asset_id: UUID, expected_version: int, now: datetime) -> bool:
        context = await self._repository.get_context(asset_id)
        if context is None:
            return False
        asset = context.asset
        if not _is_pending(asset.fetch_status, asset.parse_status, asset.version, expected_version):
            return False
        if asset.storage_key is None or asset.content_sha256 is None:
            raise RuntimeError("stored source asset metadata is incomplete")
        kind = _normalizable_kind(asset.kind)
        if kind is None:
            await self._mark_failed(asset, "UnsupportedAssetType", now)
            return False
        content = await self._blobs.read(asset.storage_key)
        try:
            result = await self._parser.parse(content, kind, self._owner_timezone)
        except AssetParseError as exc:
            if exc.failure_class == "AssetProcessingTimeout":
                raise
            await self._mark_failed(asset, exc.failure_class, now)
            return False
        await self._normalization.store_asset(
            asset.asset_id,
            asset.inbox_item_id,
            result.text,
            asset.content_sha256,
            result.parser_version,
            context.source_ref,
            result.calendar,
        )
        previous_version = asset.version
        asset.mark_parsed(result.parser_version, now)
        await self._repository.save(asset, previous_version)
        await self._jobs.enqueue(
            JobRequest(
                "knowledge-asset-index",
                {"asset_id": str(asset.asset_id), "version": asset.version},
                f"knowledge-asset-index:{asset.asset_id}:v{asset.version}",
                now,
            )
        )
        if result.calendar is not None:
            await self._jobs.enqueue(
                JobRequest(
                    "calendar-change-ingest",
                    {"asset_id": str(asset.asset_id), "version": asset.version},
                    f"calendar-change-ingest:{asset.asset_id}:v{asset.version}",
                    now,
                )
            )
        return True

    async def _mark_failed(self, asset: SourceAsset, failure_class: str, now: datetime) -> None:
        previous_version = asset.version
        asset.mark_parse_failed(failure_class, now)
        await self._repository.save(asset, previous_version)


def _is_pending(
    fetch_status: AssetFetchStatus,
    parse_status: AssetParseStatus,
    version: int,
    expected_version: int,
) -> bool:
    return (
        fetch_status is AssetFetchStatus.STORED
        and parse_status is AssetParseStatus.PENDING
        and version == expected_version
    )


def _normalizable_kind(kind: AssetKind) -> NormalizableAssetKind | None:
    try:
        return NormalizableAssetKind(kind.value)
    except ValueError:
        return None
