"""Atomic idempotent Inbox persistence and source traceability."""

from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.contracts.source import IngressType, SourceType, TrustLevel
from qq_time_agent.modules.inbox.contracts import (
    InboxContentView,
    InboxSourceDeletedError,
    InboxSourceView,
    IngestResult,
)
from qq_time_agent.modules.inbox.domain.models import InboxItem, InboxStatus, MailEnvelope
from qq_time_agent.modules.inbox.infrastructure.tables import (
    InboxConnectionStateRow,
    InboxItemRow,
    InboxRawContentRow,
    InboxSourceDeletionRow,
    InboxSyncCursorRow,
)


class SqlInboxRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

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
        raw_content_id = uuid4()
        item = InboxItem.receive(envelope, raw_content_id)
        async with self._sessions.begin() as session:
            await _lock_connection(session, envelope.connection_id)
            state = await session.scalar(
                select(InboxConnectionStateRow)
                .where(InboxConnectionStateRow.connection_id == envelope.connection_id)
                .with_for_update(read=True)
            )
            deleted_identity = InboxSourceDeletionRow.external_id == envelope.external_id
            if envelope.dedupe_key is not None:
                deleted_identity = or_(
                    deleted_identity,
                    InboxSourceDeletionRow.dedupe_key == envelope.dedupe_key,
                )
            deleted_source = await session.scalar(
                select(InboxSourceDeletionRow.connection_id).where(
                    InboxSourceDeletionRow.connection_id == envelope.connection_id,
                    deleted_identity,
                )
            )
            if (state is not None and state.blocked) or deleted_source is not None:
                raise InboxSourceDeletedError("Inbox source is blocked from ingestion")
            inserted = await session.scalar(
                insert(InboxItemRow)
                .values(**_item_values(item))
                .on_conflict_do_nothing()
                .returning(InboxItemRow.inbox_item_id)
            )
            if inserted is not None:
                session.add(
                    InboxRawContentRow(
                        raw_content_id=raw_content_id,
                        subject=subject,
                        body_text=body_text,
                        body_html=body_html,
                        mime_type=mime_type,
                        recipients=list(recipients),
                        internet_message_id=internet_message_id,
                        change_key=change_key,
                        has_attachments=has_attachments,
                        attachment_metadata=list(attachment_metadata),
                        created_at=envelope.received_at,
                    )
                )
                return IngestResult(
                    inserted,
                    True,
                    InboxStatus.RECEIVED.value,
                    _source_ref(envelope.source_type, envelope.connection_id, envelope.external_id),
                )
            identity = InboxItemRow.external_id == envelope.external_id
            if envelope.dedupe_key is not None:
                identity = or_(identity, InboxItemRow.dedupe_key == envelope.dedupe_key)
            existing = await session.scalar(
                select(InboxItemRow).where(
                    InboxItemRow.connection_id == envelope.connection_id,
                    identity,
                )
            )
            if existing is None:
                raise RuntimeError("idempotent Inbox ingest lost existing item")
            return IngestResult(
                existing.inbox_item_id,
                False,
                existing.status,
                _source_ref(
                    SourceType(existing.source_type),
                    existing.connection_id,
                    existing.external_id,
                ),
            )

    async def get(self, inbox_item_id: UUID) -> InboxItem | None:
        async with self._sessions() as session:
            row = await session.get(InboxItemRow, inbox_item_id)
            return None if row is None else _to_item(row)

    async def find_by_external(self, connection_id: UUID, external_id: str) -> IngestResult | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(InboxItemRow).where(
                    InboxItemRow.connection_id == connection_id,
                    InboxItemRow.external_id == external_id,
                )
            )
            if row is None:
                return None
            return IngestResult(
                row.inbox_item_id,
                False,
                row.status,
                _source_ref(SourceType(row.source_type), row.connection_id, row.external_id),
            )

    async def save(self, item: InboxItem, expected_version: int) -> None:
        values = _item_values(item)
        values.pop("inbox_item_id")
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(InboxItemRow)
                .where(
                    InboxItemRow.inbox_item_id == item.inbox_item_id,
                    InboxItemRow.version == expected_version,
                )
                .values(**values)
            )
            if cast("CursorResult[tuple[()]]", result).rowcount != 1:
                raise RuntimeError("Inbox item version conflict")

    async def get_content(self, inbox_item_id: UUID) -> InboxContentView | None:
        async with self._sessions() as session:
            item = await session.get(InboxItemRow, inbox_item_id)
            if item is None or item.deleted_at is not None:
                return None
            content = await session.get(InboxRawContentRow, item.raw_content_ref)
            if content is None:
                raise RuntimeError("Inbox raw content is missing")
            return InboxContentView(
                item.inbox_item_id,
                content.subject,
                content.body_text,
                content.body_html,
                content.mime_type,
                item.occurred_at,
                _source_ref(SourceType(item.source_type), item.connection_id, item.external_id),
                item.content_hash,
                item.deleted_at,
            )

    async def get_source(self, inbox_item_id: UUID) -> InboxSourceView | None:
        async with self._sessions() as session:
            item = await session.get(InboxItemRow, inbox_item_id)
            if item is None:
                return None
            content = await session.get(InboxRawContentRow, item.raw_content_ref)
            if content is None:
                raise RuntimeError("Inbox raw content is missing")
            return InboxSourceView(
                item.inbox_item_id,
                item.source_type,
                item.external_id,
                item.thread_id,
                _mask_sender(item.sender_id),
                content.subject,
                item.occurred_at,
                item.status,
                item.deleted_at is not None,
                _source_ref(SourceType(item.source_type), item.connection_id, item.external_id),
            )

    async def mark_deleted(self, connection_id: UUID, external_id: str, now: datetime) -> bool:
        async with self._sessions.begin() as session:
            await _lock_connection(session, connection_id)
            dedupe_key = await session.scalar(
                select(InboxItemRow.dedupe_key).where(
                    InboxItemRow.connection_id == connection_id,
                    InboxItemRow.external_id == external_id,
                )
            )
            await session.execute(
                insert(InboxSourceDeletionRow)
                .values(
                    connection_id=connection_id,
                    external_id=external_id,
                    dedupe_key=dedupe_key,
                    deleted_at=now,
                )
                .on_conflict_do_nothing()
            )
            result = await session.execute(
                update(InboxItemRow)
                .where(
                    InboxItemRow.connection_id == connection_id,
                    InboxItemRow.external_id == external_id,
                    InboxItemRow.deleted_at.is_(None),
                )
                .values(deleted_at=now)
            )
            return cast("CursorResult[tuple[()]]", result).rowcount == 1

    async def get_cursor(self, connection_id: UUID) -> str | None:
        async with self._sessions() as session:
            value = await session.scalar(
                select(InboxSyncCursorRow.cursor_value).where(
                    InboxSyncCursorRow.connection_id == connection_id
                )
            )
            return value

    async def save_cursor(self, connection_id: UUID, cursor: str, now: datetime) -> None:
        if not cursor or len(cursor) > 8192:
            raise ValueError("Inbox cursor must be a bounded opaque value")
        async with self._sessions.begin() as session:
            await _lock_connection(session, connection_id)
            blocked = await session.scalar(
                select(InboxConnectionStateRow.blocked).where(
                    InboxConnectionStateRow.connection_id == connection_id
                )
            )
            if blocked:
                raise InboxSourceDeletedError("Inbox connection is blocked from cursor writes")
            await session.execute(
                insert(InboxSyncCursorRow)
                .values(connection_id=connection_id, cursor_value=cursor, updated_at=now)
                .on_conflict_do_update(
                    index_elements=[InboxSyncCursorRow.connection_id],
                    set_={"cursor_value": cursor, "updated_at": now},
                )
            )

    async def list_normalized(self, limit: int) -> tuple[UUID, ...]:
        async with self._sessions() as session:
            values = await session.scalars(
                select(InboxItemRow.inbox_item_id)
                .where(
                    InboxItemRow.status == InboxStatus.NORMALIZED.value,
                    InboxItemRow.deleted_at.is_(None),
                )
                .order_by(InboxItemRow.received_at, InboxItemRow.inbox_item_id)
                .limit(limit)
            )
            return tuple(values)

    async def list_knowledge_source_ids(
        self, limit: int, after_id: UUID | None = None
    ) -> tuple[UUID, ...]:
        async with self._sessions() as session:
            statement = select(InboxItemRow.inbox_item_id).where(
                InboxItemRow.source_type.in_(
                    (
                        SourceType.MICROSOFT_MAIL.value,
                        SourceType.QQ_MAIL.value,
                        SourceType.QQ_FORWARD.value,
                        SourceType.OWNER_NOTE.value,
                    )
                ),
                (InboxItemRow.status != InboxStatus.RECEIVED.value)
                | InboxItemRow.deleted_at.is_not(None),
            )
            if after_id is not None:
                statement = statement.where(InboxItemRow.inbox_item_id > after_id)
            values = await session.scalars(
                statement.order_by(InboxItemRow.inbox_item_id).limit(limit)
            )
            return tuple(values)


def _item_values(item: InboxItem) -> dict[str, object]:
    envelope = item.envelope
    return {
        "inbox_item_id": item.inbox_item_id,
        "connection_id": envelope.connection_id,
        "user_id": envelope.user_id,
        "source_type": item.source_type.value,
        "ingress_type": item.ingress_type.value,
        "trust_level": item.trust_level.value,
        "external_id": envelope.external_id,
        "dedupe_key": envelope.dedupe_key,
        "thread_id": envelope.thread_id,
        "sender_id": envelope.sender_id,
        "sender_display": envelope.sender_display,
        "occurred_at": envelope.occurred_at,
        "received_at": envelope.received_at,
        "raw_content_ref": item.raw_content_ref,
        "content_hash": envelope.content_hash,
        "status": item.status.value,
        "failure_class": item.failure_class,
        "retry_count": item.retry_count,
        "version": item.version,
    }


def _to_item(row: InboxItemRow) -> InboxItem:
    envelope = MailEnvelope(
        row.connection_id,
        row.user_id,
        row.external_id,
        row.thread_id,
        row.sender_id,
        row.sender_display,
        row.occurred_at,
        row.received_at,
        row.content_hash,
        SourceType(row.source_type),
        IngressType(row.ingress_type),
        TrustLevel(row.trust_level),
        row.dedupe_key,
    )
    return InboxItem(
        row.inbox_item_id,
        envelope,
        row.raw_content_ref,
        InboxStatus(row.status),
        row.failure_class,
        row.retry_count,
        row.version,
    )


def _mask_sender(address: str) -> str:
    if "@" not in address:
        return "sender"
    local, domain = address.split("@", 1)
    return f"{local[:1]}***@{domain}"


def _source_ref(source_type: SourceType, connection_id: UUID, external_id: str) -> str:
    prefix = {
        SourceType.MICROSOFT_MAIL: "mail",
        SourceType.QQ_MAIL: "qq-mail",
        SourceType.QQ_FORWARD: "qq-forward",
        SourceType.OWNER_NOTE: "owner-note",
        SourceType.QQ_DIRECT: "qq",
    }[source_type]
    return f"{prefix}:{connection_id}:{external_id}"


async def _lock_connection(session: AsyncSession, connection_id: UUID) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(_lock_key(connection_id))))


def _lock_key(connection_id: UUID) -> int:
    value = connection_id.int & ((1 << 63) - 1)
    return value if value < (1 << 62) else value - (1 << 63)
