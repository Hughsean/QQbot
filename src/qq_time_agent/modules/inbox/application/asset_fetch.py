"""Bounded source asset fetch orchestration with provider routing."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.contracts.jobs import JobQueue, JobRequest
from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.connections.contracts import ConnectionSyncPort
from qq_time_agent.modules.inbox.application.asset_ports import (
    AssetBlobStore,
    SourceAssetContext,
    SourceAssetRepository,
)
from qq_time_agent.modules.inbox.contracts import (
    MailAttachmentMetadata,
    MailProvider,
    MailProviderError,
)
from qq_time_agent.modules.inbox.domain.assets import AssetFetchStatus, AssetKind, SourceAsset


class SourceAssetContentRoute(Protocol):
    async def fetch(self, context: SourceAssetContext) -> bytes: ...


@dataclass(frozen=True, slots=True)
class MailAssetRoute:
    connections: ConnectionSyncPort
    provider: MailProvider

    async def fetch(self, context: SourceAssetContext) -> bytes:
        if context.connection_id is None:
            raise RuntimeError("mail asset is missing connection context")
        asset = context.asset
        grant = await self.connections.acquire_mail_access(context.connection_id)
        descriptor = MailAttachmentMetadata(
            asset.filename,
            asset.declared_content_type,
            asset.declared_size,
            asset.provider_asset_id,
            asset.provider_locator,
            asset.transfer_encoding,
        )
        try:
            return await self.provider.fetch_attachment(
                grant.mail_credential,
                grant.account_id,
                context.message_external_id,
                descriptor,
            )
        except MailProviderError as exc:
            if exc.failure_class == "Authentication":
                await self.connections.mark_sync_reauth_required(context.connection_id)
            elif exc.failure_class in {"TransientProvider", "RateLimit"}:
                await self.connections.mark_sync_degraded(context.connection_id)
            raise


class SourceAssetFetchService:
    def __init__(
        self,
        repository: SourceAssetRepository,
        blobs: AssetBlobStore,
        jobs: JobQueue,
        routes: dict[SourceType, SourceAssetContentRoute],
        max_bytes: int,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("asset maximum bytes must be positive")
        self._repository = repository
        self._blobs = blobs
        self._jobs = jobs
        self._routes = dict(routes)
        self._max_bytes = max_bytes

    async def fetch(self, asset_id: UUID, expected_version: int, now: datetime) -> bool:
        if expected_version < 1:
            raise ValueError("asset version must be positive")
        context = await self._repository.get_context(asset_id)
        if context is None or not _is_current(context.asset, expected_version, now):
            return False
        asset = context.asset
        route = self._routes.get(context.source_type)
        failure = _preflight_failure(asset, route, self._max_bytes)
        if failure is not None:
            await self._reject(asset, failure, now)
            return False
        assert route is not None
        try:
            content = await route.fetch(context)
        except MailProviderError as exc:
            if exc.failure_class in {"AssetTooLarge", "ProviderProtocol"}:
                await self._reject(asset, exc.failure_class, now)
                return False
            raise
        detected = _detect_content_type(content)
        if len(content) > self._max_bytes or not _kind_matches(asset.kind, detected):
            await self._reject(asset, "AssetContentMismatch", now)
            return False
        await self._store_and_schedule(asset, content, detected, now)
        return True

    async def _store_and_schedule(
        self, asset: SourceAsset, content: bytes, detected: str, now: datetime
    ) -> None:
        receipt = await self._blobs.put(asset.asset_id, content)
        previous_version = asset.version
        asset.mark_stored(
            detected_content_type=detected,
            actual_size=receipt.byte_count,
            content_sha256=receipt.sha256,
            storage_key=receipt.storage_key,
            now=now,
        )
        try:
            await self._repository.save(asset, previous_version)
        except Exception:
            await self._blobs.delete(receipt.storage_key)
            raise
        await self._jobs.enqueue(
            JobRequest(
                "source-asset-parse",
                {"asset_id": str(asset.asset_id), "version": asset.version},
                f"source-asset-parse:{asset.asset_id}:v{asset.version}",
                now,
            )
        )

    async def _reject(self, asset: SourceAsset, failure_class: str, now: datetime) -> None:
        previous_version = asset.version
        asset.reject(failure_class, now)
        await self._repository.save(asset, previous_version)


def _is_current(asset: SourceAsset, expected_version: int, now: datetime) -> bool:
    return (
        asset.fetch_status is AssetFetchStatus.DISCOVERED
        and asset.version == expected_version
        and asset.purge_at > now
    )


def _preflight_failure(
    asset: SourceAsset, route: SourceAssetContentRoute | None, max_bytes: int
) -> str | None:
    if route is None or asset.kind is AssetKind.FILE:
        return "UnsupportedAssetType"
    if asset.declared_size is not None and asset.declared_size > max_bytes:
        return "AssetTooLarge"
    return None


def _detect_content_type(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    prefix = content[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").upper()
    if prefix.startswith(b"BEGIN:VCALENDAR"):
        return "text/calendar"
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    return "text/plain"


def _kind_matches(kind: AssetKind, content_type: str) -> bool:
    return (
        (kind is AssetKind.PDF and content_type == "application/pdf")
        or (kind is AssetKind.ICS and content_type == "text/calendar")
        or (kind is AssetKind.IMAGE and content_type.startswith("image/"))
        or (kind is AssetKind.TEXT and content_type == "text/plain")
    )
