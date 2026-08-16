"""Bounded deterministic RFC 5545 parsing via the maintained icalendar library."""

from datetime import date, datetime, time, timedelta
from typing import Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import Calendar, Event

from qq_time_agent.modules.normalization.contracts import (
    CalendarChangeKind,
    CalendarEventView,
    CalendarParseResult,
)

DEFAULT_MAX_BYTES = 1_048_576
DEFAULT_MAX_EVENTS = 100
MAX_TEXT = 2_000
MAX_RECURRENCE_VALUES = 200
ALLOWED_METHODS = frozenset(
    {"PUBLISH", "REQUEST", "REPLY", "ADD", "CANCEL", "REFRESH", "COUNTER", "DECLINECOUNTER"}
)


class _IcalValue(Protocol):
    def to_ical(self) -> bytes: ...


class _DateValue(Protocol):
    dt: date | datetime


class _DateList(Protocol):
    dts: list[_DateValue]


class IcalendarParser:
    def __init__(
        self, max_bytes: int = DEFAULT_MAX_BYTES, max_events: int = DEFAULT_MAX_EVENTS
    ) -> None:
        if max_bytes < 1 or max_events < 1:
            raise ValueError("calendar parser limits must be positive")
        self._max_bytes = max_bytes
        self._max_events = max_events

    def parse(self, content: bytes, default_timezone: str) -> CalendarParseResult:
        if not content or len(content) > self._max_bytes:
            raise ValueError("calendar content is empty or exceeds the size limit")
        zone = _zone(default_timezone)
        try:
            calendar = Calendar.from_ical(content)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid RFC 5545 calendar") from exc
        method = _bounded_text(calendar.get("METHOD"), "PUBLISH", 40).upper()
        if method not in ALLOWED_METHODS or calendar.errors:
            raise ValueError("calendar method or properties are invalid")
        components = [value for value in calendar.walk() if isinstance(value, Event)]
        if any(value.errors for value in components):
            raise ValueError("calendar event properties are invalid")
        if not components or len(components) > self._max_events:
            raise ValueError("calendar event count is outside the allowed range")
        events = tuple(self._event(value, method, zone) for value in components)
        return CalendarParseResult(method, events)

    def _event(self, event: Event, method: str, default_zone: ZoneInfo) -> CalendarEventView:
        uid = _bounded_text(event.get("UID"), "", 255)
        if not uid:
            raise ValueError("calendar event UID is required")
        status = _bounded_text(event.get("STATUS"), "CONFIRMED", 40).upper()
        cancelled = method == "CANCEL" or status == "CANCELLED"
        start_raw = _date_property(event, "DTSTART")
        if start_raw is None and not cancelled:
            raise ValueError("non-cancelled calendar event requires DTSTART")
        timezone = _timezone_name(event, start_raw, default_zone)
        event_zone = _zone_or_default(timezone, default_zone)
        timezone = event_zone.key
        start = _as_datetime(start_raw, event_zone)
        end = _event_end(event, start_raw, start, event_zone)
        if start is not None and end is not None and end <= start:
            raise ValueError("calendar event end must be after start")
        recurrence_id = _as_datetime(_date_property(event, "RECURRENCE-ID"), event_zone)
        return CalendarEventView(
            uid=uid,
            sequence=_sequence(event),
            change_kind=CalendarChangeKind.CANCEL if cancelled else CalendarChangeKind.UPSERT,
            status=status,
            title=_bounded_text(event.get("SUMMARY"), "Calendar event", MAX_TEXT),
            starts_at=start,
            ends_at=end,
            timezone=timezone,
            all_day=isinstance(start_raw, date) and not isinstance(start_raw, datetime),
            location=_optional_text(event.get("LOCATION"), MAX_TEXT),
            participants=_participants(event),
            recurrence_rule=_ical_property(event.get("RRULE"), 2_000),
            recurrence_dates=_recurrence_dates(event, "RDATE", event_zone),
            excluded_dates=_recurrence_dates(event, "EXDATE", event_zone),
            recurrence_id=recurrence_id,
        )


def _zone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("calendar timezone is not recognized") from exc


def _zone_or_default(value: str, default: ZoneInfo) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return default


def _date_property(event: Event, name: str) -> date | datetime | None:
    if event.get(name) is None:
        return None
    value = event.decoded(name)
    if not isinstance(value, (date, datetime)):
        raise ValueError(f"calendar {name} must be a date or datetime")
    return value


def _event_end(
    event: Event,
    start_raw: date | datetime | None,
    start: datetime | None,
    zone: ZoneInfo,
) -> datetime | None:
    if start is None:
        return None
    end_raw = _date_property(event, "DTEND")
    if end_raw is not None:
        return _as_datetime(end_raw, zone)
    duration = event.decoded("DURATION") if event.get("DURATION") is not None else None
    if duration is not None:
        if not isinstance(duration, timedelta):
            raise ValueError("calendar DURATION must be a duration")
        return start + duration
    all_day = isinstance(start_raw, date) and not isinstance(start_raw, datetime)
    return start + (timedelta(days=1) if all_day else timedelta(minutes=30))


def _as_datetime(value: date | datetime | None, zone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)
    return datetime.combine(value, time.min, zone)


def _timezone_name(event: Event, start: date | datetime | None, default: ZoneInfo) -> str:
    property_value = event.get("DTSTART")
    if property_value is not None:
        params = getattr(property_value, "params", {})
        tzid = params.get("TZID")
        if tzid:
            return str(tzid)
    if isinstance(start, datetime) and start.tzinfo is not None:
        key = getattr(start.tzinfo, "key", None)
        if isinstance(key, str):
            return key
        if start.utcoffset() == timedelta(0):
            return "UTC"
    return default.key


def _sequence(event: Event) -> int:
    value = event.decoded("SEQUENCE") if event.get("SEQUENCE") is not None else 0
    if not isinstance(value, int) or value < 0:
        raise ValueError("calendar SEQUENCE must be a non-negative integer")
    return value


def _participants(event: Event) -> tuple[str, ...]:
    values: list[object] = []
    organizer = event.get("ORGANIZER")
    if organizer is not None:
        values.append(organizer)
    attendee = event.get("ATTENDEE")
    values.extend(
        attendee if isinstance(attendee, list) else (() if attendee is None else (attendee,))
    )
    result = {_address(value) for value in values}
    result.discard("")
    return tuple(sorted(result))


def _address(value: object) -> str:
    text = str(value).strip()
    if text.lower().startswith("mailto:"):
        text = text[7:]
    return text[:320].lower()


def _recurrence_dates(event: Event, name: str, zone: ZoneInfo) -> tuple[datetime, ...]:
    raw = event.get(name)
    values = raw if isinstance(raw, list) else (() if raw is None else (raw,))
    result: list[datetime] = []
    for value in values:
        for date_value in cast(_DateList, value).dts:
            parsed = _as_datetime(date_value.dt, zone)
            if parsed is not None:
                result.append(parsed)
            if len(result) > MAX_RECURRENCE_VALUES:
                raise ValueError("calendar recurrence set exceeds the allowed range")
    return tuple(result)


def _ical_property(value: object | None, limit: int) -> str | None:
    if value is None:
        return None
    encoded = cast(_IcalValue, value).to_ical().decode("utf-8")
    if len(encoded) > limit:
        raise ValueError("calendar recurrence rule exceeds the allowed range")
    return encoded


def _bounded_text(value: object | None, default: str, limit: int) -> str:
    text = default if value is None else str(value).strip()
    if len(text) > limit:
        raise ValueError("calendar text field exceeds the allowed range")
    return text


def _optional_text(value: object | None, limit: int) -> str | None:
    text = _bounded_text(value, "", limit)
    return text or None
