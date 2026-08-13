"""SQLAlchemy table exclusively owned by Notifications."""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class NotificationsBase(DeclarativeBase):
    pass


class DeliveryRow(NotificationsBase):
    __tablename__ = "notifications_deliveries"

    idempotency_key: Mapped[str] = mapped_column(String(240), primary_key=True)
    delivery_id: Mapped[str] = mapped_column(String(512), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
