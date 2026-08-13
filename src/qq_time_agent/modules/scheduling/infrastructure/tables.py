"""SQLAlchemy table exclusively owned by Scheduling."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class SchedulingBase(DeclarativeBase):
    pass


class ProposalRow(SchedulingBase):
    __tablename__ = "scheduling_proposals"

    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    candidate_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    recommended_slot: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    alternative_slots: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    conflicts: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    source_refs: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    constraint_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (UniqueConstraint("candidate_id", name="uq_scheduling_proposal_candidate"),)
