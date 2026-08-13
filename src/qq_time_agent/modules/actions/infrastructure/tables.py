"""SQLAlchemy table exclusively owned by Actions."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ActionsBase(DeclarativeBase):
    pass


class ActionRow(ActionsBase):
    __tablename__ = "actions_requests"

    action_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    proposal_version: Mapped[int | None] = mapped_column(Integer)
    agenda_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agenda_entry_version: Mapped[int | None] = mapped_column(Integer)
    reminder_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    failure_class: Mapped[str | None] = mapped_column(String(120))

    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_actions_idempotency"),)
