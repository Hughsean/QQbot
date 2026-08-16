"""Application ports for source asset persistence and bounded blob storage."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.inbox.domain.assets import SourceAsset


@dataclass(frozen=True, slots=True)
class BlobReceipt:
    storage_key: str
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceAssetContext:
    asset: SourceAsset
    connection_id: UUID | None
    message_external_id: str
    source_type: SourceType
    source_ref: str | None


class AssetBlobStore(Protocol):
    async def put(self, asset_id: UUID, content: bytes) -> BlobReceipt: ...

    async def read(self, storage_key: str) -> bytes: ...

    async def delete(self, storage_key: str) -> None: ...


class SourceAssetRepository(Protocol):
    async def add_or_get(self, asset: SourceAsset) -> SourceAsset: ...

    async def get(self, asset_id: UUID) -> SourceAsset | None: ...

    async def get_context(self, asset_id: UUID) -> SourceAssetContext | None: ...

    async def save(self, asset: SourceAsset, expected_version: int) -> None: ...

    async def list_expired(self, now: datetime, limit: int) -> tuple[SourceAsset, ...]: ...

    async def list_pending(self, limit: int) -> tuple[SourceAsset, ...]: ...
