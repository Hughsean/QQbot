from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.inbox.application.asset_cleanup import SourceAssetCleanupService
from qq_time_agent.modules.inbox.application.asset_ports import SourceAssetContext
from qq_time_agent.modules.inbox.domain.assets import AssetKind, SourceAsset
from qq_time_agent.modules.inbox.infrastructure.blob_store import FileAssetBlobStore


@dataclass
class Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@dataclass
class Repository:
    asset: SourceAsset
    saves: list[tuple[UUID, int]] = field(default_factory=list)

    async def add_or_get(self, asset: SourceAsset) -> SourceAsset:
        return self.asset

    async def get(self, asset_id: UUID) -> SourceAsset | None:
        return self.asset if self.asset.asset_id == asset_id else None

    async def get_context(self, asset_id: UUID) -> SourceAssetContext | None:
        return None

    async def save(self, asset: SourceAsset, expected_version: int) -> None:
        assert expected_version + 1 == asset.version
        self.saves.append((asset.asset_id, expected_version))

    async def list_pending(self, limit: int) -> tuple[SourceAsset, ...]:
        return ()

    async def list_expired(self, now: datetime, limit: int) -> tuple[SourceAsset, ...]:
        assert limit == 100
        return (self.asset,) if self.asset.deleted_at is None and self.asset.purge_at <= now else ()


@pytest.mark.asyncio
async def test_cleanup_deletes_blob_before_marking_asset_deleted(tmp_path: Path) -> None:
    created_at = datetime(2026, 8, 14, tzinfo=UTC)
    asset = SourceAsset.discover(
        uuid4(),
        "asset-1",
        "part:1",
        AssetKind.PDF,
        "application/pdf",
        created_at,
        created_at + timedelta(hours=1),
    )
    blobs = FileAssetBlobStore(tmp_path, 1024)
    receipt = await blobs.put(asset.asset_id, b"%PDF-synthetic")
    asset.mark_stored(
        detected_content_type="application/pdf",
        actual_size=receipt.byte_count,
        content_sha256=receipt.sha256,
        storage_key=receipt.storage_key,
        now=created_at,
    )
    repository = Repository(asset)
    cleaned = await SourceAssetCleanupService(
        repository, blobs, Clock(created_at + timedelta(hours=1))
    ).cleanup_expired()
    assert cleaned == 1 and asset.deleted_at is not None
    assert asset.storage_key is None and repository.saves == [(asset.asset_id, 2)]
    with pytest.raises(FileNotFoundError):
        await blobs.read(receipt.storage_key)


@pytest.mark.asyncio
async def test_cleanup_is_noop_before_expiry(tmp_path: Path) -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    asset = SourceAsset.discover(
        uuid4(),
        "asset-2",
        "part:2",
        AssetKind.ICS,
        "text/calendar",
        now,
        now + timedelta(hours=24),
    )
    repository = Repository(asset)
    cleaned = await SourceAssetCleanupService(
        repository, FileAssetBlobStore(tmp_path, 1024), Clock(now)
    ).cleanup_expired()
    assert cleaned == 0 and repository.saves == []
