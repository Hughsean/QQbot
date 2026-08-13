"""Stable provider-neutral Inbox and mail synchronization contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.contracts.source import SourceEnvelope
from qq_time_agent.modules.credentials.contracts import CredentialHandle


@dataclass(frozen=True, slots=True)
class MailAddress:
    address: str
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class MailAttachmentMetadata:
    filename: str | None
    content_type: str
    declared_size: int | None


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


class MailProvider(Protocol):
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


class InboxContentPort(Protocol):
    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None: ...


class InboxSourcePort(Protocol):
    async def get_source(self, inbox_item_id: UUID) -> InboxSourceView | None: ...


class InboxProcessingPort(Protocol):
    async def mark_normalized(self, inbox_item_id: UUID) -> None: ...

    async def mark_understood(self, inbox_item_id: UUID) -> None: ...

    async def mark_needs_review(self, inbox_item_id: UUID) -> None: ...

    async def mark_ignored(self, inbox_item_id: UUID) -> None: ...

    async def mark_proposed(self, inbox_item_id: UUID) -> None: ...

    async def mark_completed(self, inbox_item_id: UUID) -> None: ...


class QqInboxPort(Protocol):
    async def ingest_qq(self, envelope: SourceEnvelope, content: str) -> IngestResult: ...


class InboxProcessingQueryPort(Protocol):
    async def list_normalized(self, limit: int) -> tuple[UUID, ...]: ...


class InboxKnowledgeQueryPort(Protocol):
    async def list_knowledge_source_ids(
        self, limit: int, after_id: UUID | None = None
    ) -> tuple[UUID, ...]: ...
