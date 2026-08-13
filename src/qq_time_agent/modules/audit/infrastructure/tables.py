"""SQLAlchemy table exclusively owned by Audit."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AuditBase(DeclarativeBase):
    pass


class AuditEventRow(AuditBase):
    __tablename__ = "audit_events"

    audit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_metadata: Mapped[dict[str, str]] = mapped_column("metadata", JSONB, nullable=False)

    __table_args__ = (Index("ix_audit_event_time", "event_type", "occurred_at"),)
