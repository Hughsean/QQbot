"""Inbox commands enforcing immutable ingest and explicit state transitions."""

import hashlib
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from qq_time_agent.contracts.source import IngressType, SourceEnvelope, SourceType, TrustLevel
from qq_time_agent.modules.inbox.application.ports import InboxRepository
from qq_time_agent.modules.inbox.contracts import (
    ConversationContextItem,
    InboxContentView,
    InboxSourceView,
    IngestResult,
    MailChange,
)
from qq_time_agent.modules.inbox.domain.models import InboxItem, InboxStatus, MailEnvelope


class InboxService:
    def __init__(self, repository: InboxRepository) -> None:
        self._repository = repository

    async def ingest_mail(
        self,
        connection_id: UUID,
        user_id: str,
        change: MailChange,
        received_at: datetime,
        source_type: SourceType = SourceType.MICROSOFT_MAIL,
    ) -> IngestResult:
        content_type = change.body_content_type.lower()
        body_text = change.body if content_type in {"text", "text/plain"} else ""
        body_html = change.body if content_type in {"html", "text/html"} else None
        content_hash = hashlib.sha256(
            (change.subject + "\0" + change.body).encode("utf-8")
        ).hexdigest()
        envelope = MailEnvelope(
            connection_id,
            user_id,
            change.external_id,
            change.thread_id,
            change.sender.address,
            change.sender.display_name,
            change.occurred_at,
            received_at,
            content_hash,
            source_type,
            IngressType.SYNC,
            TrustLevel.T2,
            change.dedupe_key,
        )
        return await self._repository.ingest(
            envelope,
            change.subject,
            body_text,
            body_html,
            change.body_content_type,
            tuple(
                {"address": recipient.address, "display_name": recipient.display_name}
                for recipient in change.recipients
            ),
            change.internet_message_id,
            change.change_key,
            change.has_attachments,
            tuple(
                {
                    "filename": item.filename,
                    "content_type": item.content_type,
                    "declared_size": item.declared_size,
                }
                for item in change.attachments
            ),
        )

    async def ingest_qq(self, envelope: SourceEnvelope, content: str) -> IngestResult:
        if envelope.source_type.value not in {"QQ_DIRECT", "QQ_FORWARD", "OWNER_NOTE"}:
            raise ValueError("QQ ingest requires a QQ source envelope")
        if not content.strip():
            raise ValueError("QQ text content is required")
        item_envelope = MailEnvelope(
            uuid5(NAMESPACE_URL, f"qq:{envelope.sender.provider_id}"),
            "owner",
            envelope.external_id,
            envelope.thread_id,
            envelope.sender.provider_id,
            envelope.sender.display,
            envelope.occurred_at,
            envelope.received_at,
            envelope.content_hash.removeprefix("sha256:"),
            envelope.source_type,
            envelope.ingress_type,
            envelope.trust_level,
        )
        return await self._repository.ingest(
            item_envelope,
            _qq_subject(envelope.source_type.value),
            content,
            None,
            "text/plain",
            (),
            None,
            None,
            False,
            (),
        )

    async def mark_normalized(self, inbox_item_id: UUID) -> None:
        item = await self._require_item(inbox_item_id)
        expected = item.version
        item.mark_normalized()
        await self._repository.save(item, expected)

    async def mark_failed(self, inbox_item_id: UUID, failure_class: str, retryable: bool) -> None:
        item = await self._require_item(inbox_item_id)
        expected = item.version
        item.mark_failed(failure_class, retryable)
        await self._repository.save(item, expected)

    async def mark_understood(self, inbox_item_id: UUID) -> None:
        await self._transition(inbox_item_id, "understood")

    async def mark_needs_review(self, inbox_item_id: UUID) -> None:
        await self._transition(inbox_item_id, "needs_review")

    async def mark_ignored(self, inbox_item_id: UUID) -> None:
        await self._transition(inbox_item_id, "ignored")

    async def mark_proposed(self, inbox_item_id: UUID) -> None:
        await self._transition(inbox_item_id, "proposed")

    async def mark_completed(self, inbox_item_id: UUID) -> None:
        item = await self._require_item(inbox_item_id)
        if item.status is InboxStatus.COMPLETED:
            return
        expected = item.version
        item.mark_completed()
        await self._repository.save(item, expected)

    async def content(self, inbox_item_id: UUID) -> InboxContentView | None:
        return await self._repository.get_content(inbox_item_id)

    async def source(self, inbox_item_id: UUID) -> InboxSourceView | None:
        return await self._repository.get_source(inbox_item_id)

    async def list_recent_conversation(
        self, user_id: str, before: datetime, exclude_id: UUID, limit: int = 8
    ) -> tuple[ConversationContextItem, ...]:
        return await self._repository.list_recent_conversation(user_id, before, exclude_id, limit)

    async def list_normalized(self, limit: int) -> tuple[UUID, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("normalized Inbox query limit must be between 1 and 100")
        return await self._repository.list_normalized(limit)

    async def list_needs_review(self, limit: int) -> tuple[InboxSourceView, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("review query limit must be between 1 and 100")
        return await self._repository.list_needs_review(limit)

    async def list_knowledge_source_ids(
        self, limit: int, after_id: UUID | None = None
    ) -> tuple[UUID, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("Knowledge Inbox query limit must be between 1 and 100")
        return await self._repository.list_knowledge_source_ids(limit, after_id)

    async def _require_item(self, inbox_item_id: UUID) -> "InboxItem":
        item = await self._repository.get(inbox_item_id)
        if item is None:
            raise LookupError("Inbox item does not exist")
        return item

    async def _transition(self, inbox_item_id: UUID, target: str) -> None:
        item = await self._require_item(inbox_item_id)
        target_status = {
            "understood": InboxStatus.UNDERSTOOD,
            "needs_review": InboxStatus.NEEDS_REVIEW,
            "ignored": InboxStatus.IGNORED,
            "proposed": InboxStatus.PROPOSED,
        }[target]
        if item.status is target_status:
            return
        expected = item.version
        transitions = {
            "understood": item.mark_understood,
            "needs_review": item.mark_needs_review,
            "ignored": item.mark_ignored,
            "proposed": item.mark_proposed,
        }
        transitions[target]()
        await self._repository.save(item, expected)


def _qq_subject(source_type: str) -> str:
    return {
        "QQ_FORWARD": "QQ 转发文本",
        "OWNER_NOTE": "主人笔记",
        "QQ_DIRECT": "QQ 直接输入",
    }[source_type]
