"""Shared, business-neutral clock contract."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return a timezone-aware current time."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()
