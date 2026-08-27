"""Shared, business-neutral clock contract."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return a timezone-aware current time."""


class SystemClock:
    def now(self) -> datetime:
        # Persist and compare instants independently of the host/container timezone.
        return datetime.now(UTC)
