"""SQLAlchemy table exclusively owned by Workflow."""

import uuid

from sqlalchemy import Float, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class WorkflowBase(DeclarativeBase):
    pass


class UnderstandingCheckpointRow(WorkflowBase):
    __tablename__ = "workflow_understanding_checkpoints"

    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    result_kind: Mapped[str | None] = mapped_column(String(20))
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confidence: Mapped[float | None] = mapped_column(Float)
    review_reason: Mapped[str | None] = mapped_column(String(120))
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512), index=True)
