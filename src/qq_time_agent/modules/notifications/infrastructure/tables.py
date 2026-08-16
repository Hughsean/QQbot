"""SQLAlchemy table exclusively owned by Notifications."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class NotificationsBase(DeclarativeBase):
    pass


class DeliveryRow(NotificationsBase):
    __tablename__ = "notifications_deliveries"

    idempotency_key: Mapped[str] = mapped_column(String(240), primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(512), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationIntentRow(NotificationsBase):
    __tablename__ = "notifications_intents"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notifications_intent_idempotency"),
        Index("ix_notifications_intent_due", "state", "available_at"),
        Index("ix_notifications_intent_subject_sent", "subject_key", "sent_at"),
    )

    intent_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(240), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    template_version: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_delivery_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer(), nullable=False)


Index(
    "uq_notifications_intent_blocking_subject",
    NotificationIntentRow.subject_key,
    unique=True,
    postgresql_where=NotificationIntentRow.state.in_(
        ("PENDING", "LEASED", "AMBIGUOUS", "DEAD_LETTER")
    ),
)
