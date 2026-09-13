"""SQLAlchemy tables exclusively owned by Task Projection."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TaskProjectionBase(DeclarativeBase):
    pass


class TaskProjectionTargetRow(TaskProjectionBase):
    __tablename__ = "task_projection_targets"
    __table_args__ = (
        UniqueConstraint("provider", "connection_id", name="uq_task_projection_target_connection"),
    )

    target_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_list_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)


class TaskProjectionMappingRow(TaskProjectionBase):
    __tablename__ = "task_projection_mappings"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "connection_id",
            "agenda_entry_id",
            name="uq_task_projection_mapping_agenda",
        ),
        UniqueConstraint(
            "provider",
            "connection_id",
            "provider_task_ref",
            name="uq_task_projection_mapping_external",
        ),
        Index("ix_task_projection_mapping_status", "status"),
    )

    mapping_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    agenda_entry_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agenda_entry_version: Mapped[int] = mapped_column(Integer(), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_list_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider_task_ref: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_revision: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    last_projected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_completion: Mapped[bool | None] = mapped_column(Boolean(), nullable=True)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)


class TaskProjectionCursorRow(TaskProjectionBase):
    __tablename__ = "task_projection_cursors"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "connection_id",
            "provider_list_ref",
            name="uq_task_projection_cursor_target",
        ),
    )

    cursor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    connection_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_list_ref: Mapped[str] = mapped_column(String(1024), nullable=False)
    opaque_cursor: Mapped[str] = mapped_column(Text(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
