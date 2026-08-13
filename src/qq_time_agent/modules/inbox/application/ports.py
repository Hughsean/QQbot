"""Private persistence ports for Inbox-owned data."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.inbox.contracts import InboxContentView, InboxSourceView, IngestResult
from qq_time_agent.modules.inbox.domain.models import InboxItem, MailEnvelope


class InboxRepository(Protocol):
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
    ) -> IngestResult: ...

    async def get(self, inbox_item_id: UUID) -> InboxItem | None: ...

    async def find_by_external(
        self, connection_id: UUID, external_id: str
    ) -> IngestResult | None: ...

    async def save(self, item: InboxItem, expected_version: int) -> None: ...

    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None: ...

    async def get_source(self, inbox_item_id: UUID) -> InboxSourceView | None: ...

    async def mark_deleted(self, connection_id: UUID, external_id: str, now: datetime) -> bool: ...

    async def get_cursor(self, connection_id: UUID) -> str | None: ...

    async def save_cursor(self, connection_id: UUID, cursor: str, now: datetime) -> None: ...

    async def list_normalized(self, limit: int) -> tuple[UUID, ...]: ...

    async def list_knowledge_source_ids(
        self, limit: int, after_id: UUID | None = None
    ) -> tuple[UUID, ...]: ...
