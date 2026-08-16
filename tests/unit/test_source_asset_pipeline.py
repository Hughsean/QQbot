from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qq_time_agent.contracts.jobs import JobLease, JobRequest, JobStatusView
from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.connections.contracts import MailAccessGrant
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.inbox.application.asset_discovery import MailAssetDiscoveryService
from qq_time_agent.modules.inbox.application.asset_fetch import (
    MailAssetRoute,
    SourceAssetFetchService,
)
from qq_time_agent.modules.inbox.application.asset_parse import SourceAssetParseService
from qq_time_agent.modules.inbox.application.asset_ports import SourceAssetContext
from qq_time_agent.modules.inbox.contracts import (
    MailAttachmentMetadata,
    MailChange,
    MailDeltaPage,
    MailProviderError,
)
from qq_time_agent.modules.inbox.domain.assets import AssetKind, SourceAsset
from qq_time_agent.modules.inbox.infrastructure.blob_store import FileAssetBlobStore
from qq_time_agent.modules.normalization.contracts import (
    AssetParseError,
    CalendarParseResult,
    NormalizableAssetKind,
    NormalizedAssetView,
    ParsedAssetContent,
)

NOW = datetime(2026, 8, 14, tzinfo=UTC)


@dataclass
class Repository:
    asset: SourceAsset
    context: SourceAssetContext
    saves: list[int] = field(default_factory=list)
    fail_save: bool = False

    async def add_or_get(self, asset: SourceAsset) -> SourceAsset:
        self.asset = asset
        return asset

    async def get(self, asset_id: UUID) -> SourceAsset | None:
        return self.asset if asset_id == self.asset.asset_id else None

    async def get_context(self, asset_id: UUID) -> SourceAssetContext | None:
        return self.context if asset_id == self.asset.asset_id else None

    async def save(self, asset: SourceAsset, expected_version: int) -> None:
        if self.fail_save:
            raise RuntimeError("synthetic stale save")
        self.saves.append(expected_version)

    async def list_expired(self, now: datetime, limit: int) -> tuple[SourceAsset, ...]:
        return ()

    async def list_pending(self, limit: int) -> tuple[SourceAsset, ...]:
        return (self.asset,)


@dataclass
class Queue:
    requests: list[JobRequest] = field(default_factory=list)

    async def enqueue(self, request: JobRequest) -> UUID:
        self.requests.append(request)
        return uuid4()

    async def lease_due(
        self, now: datetime, worker_id: str, limit: int, lease_duration: timedelta
    ) -> list[JobLease]:
        return []

    async def complete(self, lease: JobLease, now: datetime) -> None:
        return None

    async def fail(
        self,
        lease: JobLease,
        now: datetime,
        failure_class: str,
        retry_at: datetime | None,
    ) -> None:
        return None

    async def status(self, job_id: UUID) -> JobStatusView | None:
        return None


@dataclass
class Connections:
    connection_id: UUID
    states: list[str] = field(default_factory=list)

    async def acquire_mail_access(self, connection_id: UUID) -> MailAccessGrant:
        assert connection_id == self.connection_id
        return MailAccessGrant(
            connection_id,
            "owner",
            "owner@example.test",
            CredentialHandle("token", CredentialKind.ACCESS_TOKEN, NOW + timedelta(hours=1)),
        )

    async def ensure_sync_available(self, connection_id: UUID) -> None:
        return None

    async def mark_sync_succeeded(self, connection_id: UUID, completed_at: datetime) -> None:
        return None

    async def mark_sync_reauth_required(self, connection_id: UUID) -> None:
        self.states.append("REAUTH_REQUIRED")

    async def mark_sync_degraded(self, connection_id: UUID) -> None:
        self.states.append("DEGRADED")


@dataclass
class Provider:
    content: bytes
    failure_class: str | None = None

    async def fetch_page(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        cursor_url: str | None,
        since: datetime,
    ) -> MailDeltaPage:
        raise NotImplementedError

    async def fetch_content(
        self, mail_credential: CredentialHandle, account_id: str, change: MailChange
    ) -> MailChange:
        raise NotImplementedError

    async def fetch_attachment(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        message_external_id: str,
        attachment: MailAttachmentMetadata,
    ) -> bytes:
        assert attachment.provider_asset_id == "attachment-1"
        if self.failure_class is not None:
            raise MailProviderError(self.failure_class)
        return self.content


class FailedParser:
    async def parse(
        self, content: bytes, kind: NormalizableAssetKind, owner_timezone: str
    ) -> ParsedAssetContent:
        raise AssetParseError("MalformedAsset")


class Parser:
    async def parse(
        self, content: bytes, kind: NormalizableAssetKind, owner_timezone: str
    ) -> ParsedAssetContent:
        assert content.startswith(b"%PDF-") and kind is NormalizableAssetKind.PDF
        return ParsedAssetContent("Meeting Friday at 10:00", "parser-v1")


@dataclass
class Normalization:
    values: list[tuple[UUID, str]] = field(default_factory=list)

    async def store_asset(
        self,
        asset_id: UUID,
        inbox_item_id: UUID,
        text: str,
        source_hash: str,
        parser_version: str,
        source_ref: str | None,
        calendar: CalendarParseResult | None,
    ) -> NormalizedAssetView:
        self.values.append((asset_id, text))
        return NormalizedAssetView(
            asset_id, inbox_item_id, text, source_hash, parser_version, source_ref, calendar
        )


def _repository() -> tuple[Repository, UUID]:
    connection_id = uuid4()
    asset = SourceAsset.discover(
        uuid4(),
        "attachment-1",
        "attachment-1",
        AssetKind.PDF,
        "application/pdf",
        NOW,
        NOW + timedelta(hours=24),
        filename="agenda.pdf",
        declared_size=14,
    )
    context = SourceAssetContext(
        asset, connection_id, "message-1", SourceType.MICROSOFT_MAIL, "mail:source"
    )
    return Repository(asset, context), connection_id


@pytest.mark.asyncio
async def test_discovery_is_idempotent_and_recovers_pending_jobs() -> None:
    repository, _ = _repository()
    queue = Queue()
    service = MailAssetDiscoveryService(repository, queue, 24)
    descriptor = MailAttachmentMetadata(
        "agenda.pdf", "application/pdf", 14, "attachment-1", "attachment-1"
    )
    asset_ids = await service.discover(repository.asset.inbox_item_id, (descriptor,), NOW)
    assert asset_ids == (repository.asset.asset_id,)
    assert queue.requests[0].payload == {
        "asset_id": str(repository.asset.asset_id),
        "version": 1,
    }
    assert await service.recover_pending(NOW) == 1
    assert len(queue.requests) == 2


@pytest.mark.asyncio
async def test_fetch_stores_bounded_blob_and_schedules_parse(tmp_path: Path) -> None:
    repository, connection_id = _repository()
    queue = Queue()
    blobs = FileAssetBlobStore(tmp_path, 1024)
    service = SourceAssetFetchService(
        repository,
        blobs,
        queue,
        {
            SourceType.MICROSOFT_MAIL: MailAssetRoute(
                Connections(connection_id), Provider(b"%PDF-synthetic")
            )
        },
        1024,
    )
    assert await service.fetch(repository.asset.asset_id, 1, NOW)
    assert repository.asset.storage_key is not None
    assert queue.requests[-1].kind == "source-asset-parse"


@pytest.mark.asyncio
async def test_parse_persists_text_marks_asset_and_schedules_knowledge(tmp_path: Path) -> None:
    repository, _ = _repository()
    blobs = FileAssetBlobStore(tmp_path, 1024)
    receipt = await blobs.put(repository.asset.asset_id, b"%PDF-synthetic")
    repository.asset.mark_stored(
        detected_content_type="application/pdf",
        actual_size=receipt.byte_count,
        content_sha256=receipt.sha256,
        storage_key=receipt.storage_key,
        now=NOW,
    )
    normalization = Normalization()
    queue = Queue()
    service = SourceAssetParseService(
        repository, blobs, Parser(), normalization, queue, "Asia/Shanghai"
    )
    assert await service.parse(repository.asset.asset_id, 2, NOW)
    assert normalization.values == [(repository.asset.asset_id, "Meeting Friday at 10:00")]
    assert queue.requests[-1].kind == "knowledge-asset-index"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "maximum", "failure_class"),
    ((b"plain text mismatch", 1024, "AssetContentMismatch"), (b"%PDF-ok", 8, "AssetTooLarge")),
)
async def test_fetch_rejects_mismatched_and_declared_oversized_assets(
    tmp_path: Path, content: bytes, maximum: int, failure_class: str
) -> None:
    repository, connection_id = _repository()
    service = SourceAssetFetchService(
        repository,
        FileAssetBlobStore(tmp_path, 1024),
        Queue(),
        {SourceType.MICROSOFT_MAIL: MailAssetRoute(Connections(connection_id), Provider(content))},
        maximum,
    )
    assert not await service.fetch(repository.asset.asset_id, 1, NOW)
    assert repository.asset.failure_class == failure_class


@pytest.mark.asyncio
async def test_fetch_marks_provider_auth_failure_and_keeps_asset_retryable(tmp_path: Path) -> None:
    repository, connection_id = _repository()
    connections = Connections(connection_id)
    service = SourceAssetFetchService(
        repository,
        FileAssetBlobStore(tmp_path, 1024),
        Queue(),
        {SourceType.MICROSOFT_MAIL: MailAssetRoute(connections, Provider(b"", "Authentication"))},
        1024,
    )
    with pytest.raises(MailProviderError, match="Authentication"):
        await service.fetch(repository.asset.asset_id, 1, NOW)
    assert connections.states == ["REAUTH_REQUIRED"]
    assert repository.asset.version == 1


@pytest.mark.asyncio
async def test_fetch_deletes_blob_when_metadata_save_loses_race(tmp_path: Path) -> None:
    repository, connection_id = _repository()
    repository.fail_save = True
    blobs = FileAssetBlobStore(tmp_path, 1024)
    service = SourceAssetFetchService(
        repository,
        blobs,
        Queue(),
        {
            SourceType.MICROSOFT_MAIL: MailAssetRoute(
                Connections(connection_id), Provider(b"%PDF-synthetic")
            )
        },
        1024,
    )
    with pytest.raises(RuntimeError, match="stale save"):
        await service.fetch(repository.asset.asset_id, 1, NOW)
    assert repository.asset.storage_key is not None
    with pytest.raises(FileNotFoundError):
        await blobs.read(repository.asset.storage_key)


@pytest.mark.asyncio
async def test_parse_marks_malformed_asset_terminal_without_scheduling(tmp_path: Path) -> None:
    repository, _ = _repository()
    blobs = FileAssetBlobStore(tmp_path, 1024)
    receipt = await blobs.put(repository.asset.asset_id, b"%PDF-malformed")
    repository.asset.mark_stored(
        detected_content_type="application/pdf",
        actual_size=receipt.byte_count,
        content_sha256=receipt.sha256,
        storage_key=receipt.storage_key,
        now=NOW,
    )
    queue = Queue()
    service = SourceAssetParseService(
        repository, blobs, FailedParser(), Normalization(), queue, "Asia/Shanghai"
    )
    assert not await service.parse(repository.asset.asset_id, 2, NOW)
    assert repository.asset.failure_class == "MalformedAsset"
    assert queue.requests == []
