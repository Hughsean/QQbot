"""Restart-safe cleanup of expired raw source asset blobs."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.inbox.application.asset_ports import (
    AssetBlobStore,
    SourceAssetRepository,
)


class SourceAssetCleanupService:
    def __init__(
        self,
        repository: SourceAssetRepository,
        blobs: AssetBlobStore,
        clock: Clock,
        batch_size: int = 100,
    ) -> None:
        if batch_size < 1 or batch_size > 500:
            raise ValueError("asset cleanup batch size must be between 1 and 500")
        self._repository = repository
        self._blobs = blobs
        self._clock = clock
        self._batch_size = batch_size

    async def cleanup_expired(self) -> int:
        now = self._clock.now()
        assets = await self._repository.list_expired(now, self._batch_size)
        deleted = 0
        for asset in assets:
            expected_version = asset.version
            if asset.storage_key is not None:
                await self._blobs.delete(asset.storage_key)
            asset.mark_deleted(now)
            await self._repository.save(asset, expected_version)
            deleted += 1
        return deleted
