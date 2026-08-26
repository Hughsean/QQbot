from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.connections.contracts import MailAccessGrant
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.application.sync import MailSyncService
from qq_time_agent.modules.inbox.contracts import (
    ConversationContextItem,
    InboxContentView,
    InboxSourceView,
    IngestResult,
    MailAddress,
    MailChange,
    MailDeltaPage,
    MailProviderError,
)
from qq_time_agent.modules.inbox.domain.models import InboxItem, MailEnvelope
from qq_time_agent.modules.normalization.contracts import NormalizedContentView


@dataclass
class FixedClock:
    value: datetime = datetime(2026, 8, 13, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@dataclass
class FakeConnections:
    connection_id: UUID
    reauth: bool = False
    sync_completed_at: datetime | None = None
    degraded: bool = False

    async def acquire_mail_access(self, connection_id: UUID) -> MailAccessGrant:
        assert connection_id == self.connection_id
        handle = CredentialHandle(
            "access", CredentialKind.ACCESS_TOKEN, datetime(2026, 8, 14, tzinfo=UTC)
        )
        return MailAccessGrant(connection_id, "owner", "account-id", handle)

    async def ensure_sync_available(self, connection_id: UUID) -> None:
        assert connection_id == self.connection_id

    async def mark_sync_succeeded(self, connection_id: UUID, completed_at: datetime) -> None:
        assert connection_id == self.connection_id
        self.sync_completed_at = completed_at

    async def mark_sync_reauth_required(self, connection_id: UUID) -> None:
        assert connection_id == self.connection_id
        self.reauth = True

    async def mark_sync_degraded(self, connection_id: UUID) -> None:
        assert connection_id == self.connection_id
        self.degraded = True


@dataclass
class MemoryInboxRepository:
    items: dict[UUID, InboxItem] = field(default_factory=dict)
    external: dict[tuple[UUID, str], UUID] = field(default_factory=dict)
    contents: dict[UUID, InboxContentView] = field(default_factory=dict)
    cursor: str | None = None
    cursor_writes: list[str] = field(default_factory=list)
    deleted: set[str] = field(default_factory=set)

    async def ingest(
        self,
        envelope: MailEnvelope,
        subject: str,
        body_text: str,
        body_html: str | None,
        mime_type: str,
        recipients: tuple[dict[str, str | None], ...],
        internet_message_id: str | None,
        change_key: str | None,
        has_attachments: bool,
        attachment_metadata: tuple[dict[str, object], ...],
    ) -> IngestResult:
        key = (envelope.connection_id, envelope.external_id)
        if key in self.external:
            item = self.items[self.external[key]]
            return IngestResult(item.inbox_item_id, False, item.status.value)
        item = InboxItem.receive(envelope, uuid4())
        self.items[item.inbox_item_id] = item
        self.external[key] = item.inbox_item_id
        self.contents[item.inbox_item_id] = InboxContentView(
            item.inbox_item_id,
            subject,
            body_text,
            body_html,
            mime_type,
            envelope.occurred_at,
            f"mail:{envelope.external_id}",
            envelope.content_hash,
            None,
        )
        return IngestResult(item.inbox_item_id, True, item.status.value)

    async def get(self, inbox_item_id: UUID) -> InboxItem | None:
        return self.items.get(inbox_item_id)

    async def find_by_external(self, connection_id: UUID, external_id: str) -> IngestResult | None:
        item_id = self.external.get((connection_id, external_id))
        if item_id is None:
            return None
        item = self.items[item_id]
        return IngestResult(item_id, False, item.status.value)

    async def save(self, item: InboxItem, expected_version: int) -> None:
        assert item.version == expected_version + 1
        self.items[item.inbox_item_id] = item

    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None:
        return self.contents.get(inbox_item_id)

    async def get_source(self, inbox_item_id: UUID) -> InboxSourceView | None:
        return None

    async def list_recent_conversation(
        self, user_id: str, before: datetime, exclude_id: UUID, limit: int = 8
    ) -> tuple[ConversationContextItem, ...]:
        del user_id, before, exclude_id, limit
        return ()

    async def mark_deleted(self, connection_id: UUID, external_id: str, now: datetime) -> bool:
        if (connection_id, external_id) not in self.external:
            return False
        self.deleted.add(external_id)
        return True

    async def get_cursor(self, connection_id: UUID) -> str | None:
        return self.cursor

    async def save_cursor(self, connection_id: UUID, cursor: str, now: datetime) -> None:
        self.cursor = cursor
        self.cursor_writes.append(cursor)

    async def list_normalized(self, limit: int) -> tuple[UUID, ...]:
        return tuple(
            item_id for item_id, item in self.items.items() if item.status.value == "NORMALIZED"
        )[:limit]

    async def list_needs_review(self, limit: int) -> tuple[InboxSourceView, ...]:
        del limit
        return ()

    async def list_knowledge_source_ids(
        self, limit: int, after_id: UUID | None = None
    ) -> tuple[UUID, ...]:
        values = sorted(self.items)
        if after_id is not None:
            values = [value for value in values if value > after_id]
        return tuple(values[:limit])


@dataclass
class MemoryNormalization:
    values: dict[UUID, NormalizedContentView] = field(default_factory=dict)
    fail: bool = False

    async def normalize(
        self,
        inbox_item_id: UUID,
        subject: str,
        body_text: str,
        body_html: str | None,
        source_hash: str,
        source_ref: str | None = None,
    ) -> NormalizedContentView:
        if self.fail:
            raise RuntimeError("normalizer unavailable")
        value = NormalizedContentView(
            inbox_item_id, subject, body_text, source_hash, "test-v1", source_ref
        )
        self.values[inbox_item_id] = value
        return value


@dataclass
class FakeProvider:
    pages: list[MailDeltaPage]
    failure: str | None = None
    content_failure: str | None = None
    cursors_seen: list[str | None] = field(default_factory=list)

    async def fetch_page(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        cursor_url: str | None,
        since: datetime,
    ) -> MailDeltaPage:
        assert account_id == "account-id"
        assert mail_credential.reveal(datetime(2026, 8, 13, tzinfo=UTC)) == "access"
        self.cursors_seen.append(cursor_url)
        if self.failure is not None:
            raise MailProviderError(self.failure)
        return self.pages.pop(0)

    async def fetch_content(
        self, mail_credential: CredentialHandle, account_id: str, change: MailChange
    ) -> MailChange:
        assert account_id == "account-id"
        assert mail_credential.reveal(datetime(2026, 8, 13, tzinfo=UTC)) == "access"
        if self.content_failure is not None:
            raise MailProviderError(self.content_failure)
        return change


def _mail(external_id: str, removed: bool = False) -> MailChange:
    return MailChange(
        external_id,
        "thread",
        None,
        MailAddress("sender@example.test", "Sender"),
        (MailAddress("owner@example.test"),),
        "Subject",
        "Body",
        "text",
        datetime(2026, 8, 12, tzinfo=UTC),
        "change",
        False,
        removed,
    )


def _service(
    provider: FakeProvider,
) -> tuple[MailSyncService, FakeConnections, MemoryInboxRepository, MemoryNormalization]:
    connection_id = uuid4()
    connections = FakeConnections(connection_id)
    repository = MemoryInboxRepository()
    normalization = MemoryNormalization()
    service = MailSyncService(
        connections,
        InboxService(repository),
        repository,
        normalization,
        provider,
        FixedClock(),
        7,
    )
    return service, connections, repository, normalization


@pytest.mark.asyncio
async def test_sync_pages_ingest_normalize_dedupe_delete_and_advance_cursor() -> None:
    first_url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?skip=1"
    delta_url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?delta=2"
    provider = FakeProvider(
        [
            MailDeltaPage((_mail("one"),), first_url, False),
            MailDeltaPage((_mail("one"), _mail("one", True)), delta_url, True),
        ]
    )
    service, connections, repository, normalization = _service(provider)
    result = await service.synchronize(connections.connection_id)
    assert (result.created, result.duplicates, result.deleted, result.pages) == (1, 1, 1, 2)
    assert repository.cursor_writes == [first_url, delta_url]
    assert provider.cursors_seen == [None, first_url]
    assert len(normalization.values) == 1
    assert connections.sync_completed_at == datetime(2026, 8, 13, tzinfo=UTC)


@pytest.mark.asyncio
async def test_authentication_failure_marks_connection_and_does_not_advance_cursor() -> None:
    provider = FakeProvider([], "Authentication")
    service, connections, repository, _ = _service(provider)
    with pytest.raises(MailProviderError, match="Authentication"):
        await service.synchronize(connections.connection_id)
    assert connections.reauth
    assert repository.cursor_writes == []


@pytest.mark.asyncio
async def test_content_failure_does_not_create_item_or_advance_cursor() -> None:
    delta_url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?delta=1"
    provider = FakeProvider([MailDeltaPage((_mail("one"),), delta_url, True)])
    provider.content_failure = "TransientProvider"
    service, connections, repository, _ = _service(provider)

    with pytest.raises(MailProviderError, match="TransientProvider"):
        await service.synchronize(connections.connection_id)

    assert repository.items == {}
    assert repository.cursor_writes == []
    assert connections.degraded


@pytest.mark.asyncio
async def test_normalization_failure_retries_existing_item_without_duplication() -> None:
    delta_url = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?delta=1"
    first_provider = FakeProvider([MailDeltaPage((_mail("one"),), delta_url, True)])
    service, connections, repository, normalization = _service(first_provider)
    normalization.fail = True

    with pytest.raises(MailProviderError, match="Normalization"):
        await service.synchronize(connections.connection_id)

    item = next(iter(repository.items.values()))
    assert item.status.value == "FAILED_RETRYABLE"
    assert repository.cursor_writes == []

    normalization.fail = False
    retry_provider = FakeProvider([MailDeltaPage((_mail("one"),), delta_url, True)])
    retry_service = MailSyncService(
        connections,
        InboxService(repository),
        repository,
        normalization,
        retry_provider,
        FixedClock(),
        7,
    )
    result = await retry_service.synchronize(connections.connection_id)

    assert result.created == 0
    assert result.duplicates == 1
    assert len(repository.items) == 1
    assert next(iter(repository.items.values())).status.value == "NORMALIZED"
    assert repository.cursor_writes == [delta_url]


def test_sync_requires_positive_lookback() -> None:
    provider = FakeProvider([])
    _, connections, repository, normalization = _service(provider)
    with pytest.raises(ValueError, match="positive"):
        MailSyncService(
            connections,
            InboxService(repository),
            repository,
            normalization,
            provider,
            FixedClock(),
            0,
        )
