"""Tables owned by the Agent runtime."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AgentBase(DeclarativeBase):
    pass


class AgentRunRow(AgentBase):
    __tablename__ = "agent_runs"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    observations: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    final_content: Mapped[str | None] = mapped_column(Text)
    failure_class: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("inbox_item_id", name="uq_agent_runs_inbox_item"),)


class AgentToolCallRow(AgentBase):
    __tablename__ = "agent_tool_calls"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    call_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    observation: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
