from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from qq_time_agent.contracts.source import TrustLevel
from qq_time_agent.modules.inbox.domain.assets import (
    AssetFetchStatus,
    AssetKind,
    AssetParseStatus,
    SourceAsset,
)
from qq_time_agent.modules.inbox.infrastructure.blob_store import FileAssetBlobStore


def _asset() -> SourceAsset:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    return SourceAsset.discover(
        uuid4(),
        "attachment-1",
        "part:2",
        AssetKind.PDF,
        "application/pdf",
        now,
        now + timedelta(hours=24),
        filename="agenda.pdf",
        declared_size=12,
    )


def test_source_asset_lifecycle_is_t2_and_versioned() -> None:
    asset = _asset()
    now = datetime(2026, 8, 14, tzinfo=UTC)
    assert asset.trust_level is TrustLevel.T2
    assert asset.fetch_status is AssetFetchStatus.DISCOVERED

    asset.mark_stored(
        detected_content_type="application/pdf",
        actual_size=12,
        content_sha256="a" * 64,
        storage_key=f"aa/{asset.asset_id.hex}",
        now=now,
    )
    asset.mark_parsed("pypdf-v1", now)
    assert asset.parse_status is AssetParseStatus.PARSED
    assert asset.version == 3

    asset.mark_deleted(now)
    assert asset.fetch_status.value == AssetFetchStatus.DELETED.value
    assert asset.parse_status.value == AssetParseStatus.DELETED.value
    assert asset.storage_key is None


def test_source_asset_rejects_unbounded_or_invalid_metadata() -> None:
    now = datetime(2026, 8, 14, tzinfo=UTC)
    with pytest.raises(ValueError, match="purge time"):
        SourceAsset.discover(uuid4(), "asset", "part:1", AssetKind.FILE, "text/plain", now, now)
    asset = _asset()
    with pytest.raises(ValueError, match="sha256"):
        asset.mark_stored(
            detected_content_type="application/pdf",
            actual_size=1,
            content_sha256="invalid",
            storage_key="key",
            now=now,
        )


@pytest.mark.asyncio
async def test_file_blob_store_uses_opaque_bounded_paths(tmp_path: Path) -> None:
    store = FileAssetBlobStore(tmp_path, max_bytes=16)
    asset_id = uuid4()
    receipt = await store.put(asset_id, b"synthetic")
    assert receipt.storage_key.endswith(asset_id.hex)
    assert receipt.byte_count == 9
    assert await store.read(receipt.storage_key) == b"synthetic"

    await store.put(asset_id, b"synthetic")
    with pytest.raises(ValueError, match="different content"):
        await store.put(asset_id, b"different")
    with pytest.raises(ValueError, match="storage key"):
        await store.read("../outside")
    with pytest.raises(ValueError, match="outside the allowed range"):
        await store.put(uuid4(), b"x" * 17)

    await store.delete(receipt.storage_key)
    assert not tuple(tmp_path.rglob(asset_id.hex))
