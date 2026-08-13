"""SQLAlchemy table exclusively owned by Identity."""

from datetime import time

from sqlalchemy import Integer, String, Time
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
