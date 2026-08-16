"""Public deterministic RFC 5545 calendar parsing contract."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class CalendarChangeKind(StrEnum):
    UPSERT = "UPSERT"
    CANCEL = "CANCEL"


@dataclass(frozen=True, slots=True)
class CalendarEventView:
    uid: str
    sequence: int
    change_kind: CalendarChangeKind
    status: str
    title: str
    starts_at: datetime | None
    ends_at: datetime | None
    timezone: str
    all_day: bool
    location: str | None
    participants: tuple[str, ...]
    recurrence_rule: str | None
    recurrence_dates: tuple[datetime, ...]
    excluded_dates: tuple[datetime, ...]
    recurrence_id: datetime | None


@dataclass(frozen=True, slots=True)
class CalendarParseResult:
    method: str
    events: tuple[CalendarEventView, ...]


class CalendarParserPort(Protocol):
    def parse(self, content: bytes, default_timezone: str) -> CalendarParseResult: ...
