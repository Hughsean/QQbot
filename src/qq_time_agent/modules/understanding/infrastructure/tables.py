"""SQLAlchemy table exclusively owned by Understanding."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
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
