"""SQLAlchemy table exclusively owned by Identity."""

from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, Integer, String, Time
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class IdentityBase(DeclarativeBase):
    pass


class UserPreferencesRow(IdentityBase):
    __tablename__ = "identity_user_preferences"

    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    work_start: Mapped[time] = mapped_column(Time(), nullable=False)
    work_end: Mapped[time] = mapped_column(Time(), nullable=False)
    lunch_start: Mapped[time] = mapped_column(Time(), nullable=False)
    lunch_end: Mapped[time] = mapped_column(Time(), nullable=False)
    working_weekdays: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    default_event_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    default_task_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    digest_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    digest_local_time: Mapped[time] = mapped_column(Time(), nullable=False)
    conflict_notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reauth_notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    quiet_start: Mapped[time] = mapped_column(Time(), nullable=False)
    quiet_end: Mapped[time] = mapped_column(Time(), nullable=False)


class OwnerGroupAliasRow(IdentityBase):
    __tablename__ = "identity_owner_group_aliases"

    user_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    normalized_alias: Mapped[str] = mapped_column(String(128), primary_key=True)
    alias: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
