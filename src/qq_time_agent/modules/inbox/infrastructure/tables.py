"""SQLAlchemy tables exclusively owned by Inbox."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class InboxBase(DeclarativeBase):
    pass


class InboxItemRow(InboxBase):
    __tablename__ = "inbox_items"

    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    ingress_type: Mapped[str] = mapped_column(String(40), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(10), nullable=False)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(512))
    thread_id: Mapped[str | None] = mapped_column(String(512))
    sender_id: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_display: Mapped[str | None] = mapped_column(String(320))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_content_ref: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_class: Mapped[str | None] = mapped_column(String(80))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("connection_id", "external_id", name="uq_inbox_connection_external"),
        UniqueConstraint("connection_id", "dedupe_key", name="uq_inbox_connection_dedupe"),
        Index("ix_inbox_status_received", "status", "received_at"),
    )


class InboxRawContentRow(InboxBase):
    __tablename__ = "inbox_raw_contents"

    raw_content_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    recipients: Mapped[list[dict[str, str | None]]] = mapped_column(JSONB, nullable=False)
    internet_message_id: Mapped[str | None] = mapped_column(String(998))
    change_key: Mapped[str | None] = mapped_column(String(512))
    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attachment_metadata: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InboxSyncCursorRow(InboxBase):
    __tablename__ = "inbox_sync_cursors"

    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    cursor_value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InboxConnectionStateRow(InboxBase):
    __tablename__ = "inbox_connection_states"

    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InboxSourceDeletionRow(InboxBase):
    __tablename__ = "inbox_source_deletions"

    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    external_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(512), index=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
