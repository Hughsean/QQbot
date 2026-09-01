"""Stable provider-neutral Inbox and mail synchronization contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.contracts.source import SourceAssetDescriptor, SourceEnvelope
from qq_time_agent.modules.credentials.contracts import CredentialHandle


@dataclass(frozen=True, slots=True)
class MailAddress:
    address: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True, init=False)
class MailAttachmentMetadata(SourceAssetDescriptor):
    def __init__(
        self,
        filename: str | None,
        content_type: str,
        declared_size: int | None,
        provider_asset_id: str = "",
        provider_locator: str = "",
        transfer_encoding: str | None = None,
    ) -> None:
        SourceAssetDescriptor.__init__(
            self,
            provider_asset_id,
            provider_locator,
            filename,
            content_type,
            declared_size,
            transfer_encoding,
        )


@dataclass(frozen=True, slots=True)
class MailChange:
    external_id: str
    thread_id: str | None
    internet_message_id: str | None
    sender: MailAddress
    recipients: tuple[MailAddress, ...]
    subject: str
    body: str
    body_content_type: str
    occurred_at: datetime
    change_key: str | None
    has_attachments: bool
    removed: bool = False
    dedupe_key: str | None = None
    attachments: tuple[MailAttachmentMetadata, ...] = ()


@dataclass(frozen=True, slots=True)
class MailDeltaPage:
    changes: tuple[MailChange, ...]
    continuation_url: str
    round_complete: bool


class MailSyncProvider(Protocol):
    async def fetch_page(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        cursor: str | None,
        since: datetime,
    ) -> MailDeltaPage: ...

    async def fetch_content(
        self, mail_credential: CredentialHandle, account_id: str, change: MailChange
    ) -> MailChange: ...


class MailProvider(MailSyncProvider, Protocol):
    async def fetch_attachment(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        message_external_id: str,
        attachment: MailAttachmentMetadata,
    ) -> bytes: ...


class MailProviderError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


class InboxSourceDeletedError(RuntimeError):
    """Raised when a disconnected or tombstoned source attempts re-ingestion."""


@dataclass(frozen=True, slots=True)
class IngestResult:
    inbox_item_id: UUID
    created: bool
    status: str
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class MailSyncResult:
    created: int
    duplicates: int
    deleted: int
    pages: int
    round_complete: bool


@dataclass(frozen=True, slots=True)
class InboxContentView:
    inbox_item_id: UUID
    subject: str
    body_text: str
    body_html: str | None
    mime_type: str
    occurred_at: datetime
    source_ref: str
    content_hash: str
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class InboxSourceView:
    inbox_item_id: UUID
    source_type: str
    external_id: str
    thread_id: str | None
    sender_mask: str
    subject: str
    occurred_at: datetime
    status: str
    deleted: bool
    source_ref: str | None = None


@dataclass(frozen=True, slots=True)
class MailDeliverySourceView:
    inbox_item_id: UUID
    source_type: str
    sender: str
    subject: str


class MailDeliverySourcePort(Protocol):
    async def get_mail_delivery_source(
        self, user_id: str, inbox_item_id: UUID
    ) -> MailDeliverySourceView | None: ...


@dataclass(frozen=True, slots=True)
class MailDigestTitleView:
    inbox_item_id: UUID
    subject: str


class MailDigestTitleQueryPort(Protocol):
    async def list_mail_digest_titles(
        self, user_id: str, inbox_item_ids: tuple[UUID, ...], limit: int = 20
    ) -> tuple[MailDigestTitleView, ...]: ...


@dataclass(frozen=True, slots=True)
class RecentMailItemView:
    inbox_item_id: UUID
    source_type: str
    subject: str
    sender_mask: str
    occurred_at: datetime
    status: str
    deleted: bool
    source_ref: str | None = None


class RecentMailQueryPort(Protocol):
    async def list_recent_mail(
        self, user_id: str, limit: int = 10, keyword: str | None = None
    ) -> tuple[RecentMailItemView, ...]: ...
@dataclass(frozen=True, slots=True)
class ConversationContextItem:
    source_type: str
    occurred_at: datetime
    subject: str
    body: str
    source_ref: str


class InboxContentPort(Protocol):
    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None: ...


class InboxSourcePort(Protocol):
    async def get_source(self, inbox_item_id: UUID) -> InboxSourceView | None: ...


class ConversationContextPort(Protocol):
    async def list_recent_conversation(
        self, user_id: str, before: datetime, exclude_id: UUID, limit: int = 8
    ) -> tuple[ConversationContextItem, ...]: ...


class InboxProcessingPort(Protocol):
    async def mark_normalized(self, inbox_item_id: UUID) -> None: ...

    async def mark_understood(self, inbox_item_id: UUID) -> None: ...

    async def mark_needs_review(self, inbox_item_id: UUID) -> None: ...

    async def mark_ignored(self, inbox_item_id: UUID) -> None: ...

    async def mark_proposed(self, inbox_item_id: UUID) -> None: ...

    async def mark_completed(self, inbox_item_id: UUID) -> None: ...


class QqInboxPort(Protocol):
    async def ingest_qq(
        self, envelope: SourceEnvelope, content: str, *, has_assets: bool = False
    ) -> IngestResult: ...


class InboxProcessingQueryPort(Protocol):
    async def list_normalized(self, limit: int) -> tuple[UUID, ...]: ...

    async def list_needs_review(self, limit: int) -> tuple[InboxSourceView, ...]: ...


class InboxKnowledgeQueryPort(Protocol):
    async def list_knowledge_source_ids(
        self, limit: int, after_id: UUID | None = None
    ) -> tuple[UUID, ...]: ...
