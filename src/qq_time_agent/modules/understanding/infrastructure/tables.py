"""SQLAlchemy table exclusively owned by Understanding."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UnderstandingBase(DeclarativeBase):
    pass


class CandidateRow(UnderstandingBase):
    __tablename__ = "understanding_candidates"

    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    location: Mapped[str | None] = mapped_column(String(300))
    participants: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[str | None] = mapped_column(String(20))
    allowed_windows: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    evidence: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    source_refs: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(512), nullable=False, index=True)

    __table_args__ = (UniqueConstraint("inbox_item_id", name="uq_understanding_candidate_inbox"),)


class CalendarChangeCandidateRow(UnderstandingBase):
    __tablename__ = "understanding_calendar_change_candidates"

    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    external_event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    location: Mapped[str | None] = mapped_column(Text)
    participants: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    recurrence_rule: Mapped[str | None] = mapped_column(Text)
    agenda_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    parent_source_ref: Mapped[str | None] = mapped_column(String(512), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("version_key", name="uq_understanding_calendar_version"),
        Index(
            "ix_understanding_calendar_event_sequence",
            "external_event_key",
            "sequence",
        ),
    )
