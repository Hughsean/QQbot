"""Lossless bounded JSON mapping for parsed calendar values."""

from datetime import datetime

from qq_time_agent.modules.normalization.contracts import (
    CalendarChangeKind,
    CalendarEventView,
    CalendarParseResult,
)


def calendar_to_json(value: CalendarParseResult | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "method": value.method,
        "events": [
            {
                "uid": event.uid,
                "sequence": event.sequence,
                "change_kind": event.change_kind.value,
                "status": event.status,
                "title": event.title,
                "starts_at": _format(event.starts_at),
                "ends_at": _format(event.ends_at),
                "timezone": event.timezone,
                "all_day": event.all_day,
                "location": event.location,
                "participants": list(event.participants),
                "recurrence_rule": event.recurrence_rule,
                "recurrence_dates": [_format(item) for item in event.recurrence_dates],
                "excluded_dates": [_format(item) for item in event.excluded_dates],
                "recurrence_id": _format(event.recurrence_id),
            }
            for event in value.events
        ],
    }


def calendar_from_json(value: dict[str, object] | None) -> CalendarParseResult | None:
    if value is None:
        return None
    method = value.get("method")
    events = value.get("events")
    if not isinstance(method, str) or not isinstance(events, list):
        raise ValueError("invalid stored calendar payload")
    return CalendarParseResult(method, tuple(_event(item) for item in events))


def _event(value: object) -> CalendarEventView:
    if not isinstance(value, dict):
        raise ValueError("invalid stored calendar event")
    participants = value.get("participants")
    recurrence_dates = value.get("recurrence_dates")
    excluded_dates = value.get("excluded_dates")
    if not isinstance(participants, list):
        raise ValueError("invalid stored calendar participants")
    if not isinstance(recurrence_dates, list) or not isinstance(excluded_dates, list):
        raise ValueError("invalid stored calendar recurrence dates")
    return CalendarEventView(
        uid=_string(value, "uid"),
        sequence=_integer(value, "sequence"),
        change_kind=CalendarChangeKind(_string(value, "change_kind")),
        status=_string(value, "status"),
        title=_string(value, "title"),
        starts_at=_datetime(value.get("starts_at")),
        ends_at=_datetime(value.get("ends_at")),
        timezone=_string(value, "timezone"),
        all_day=_boolean(value, "all_day"),
        location=_optional_string(value.get("location")),
        participants=tuple(_strings(participants)),
        recurrence_rule=_optional_string(value.get("recurrence_rule")),
        recurrence_dates=tuple(_datetimes(recurrence_dates)),
        excluded_dates=tuple(_datetimes(excluded_dates)),
        recurrence_id=_datetime(value.get("recurrence_id")),
    )


def _format(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid stored calendar datetime")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stored calendar datetime must be timezone-aware")
    return parsed


def _datetimes(values: list[object]) -> list[datetime]:
    result = [_datetime(value) for value in values]
    if any(value is None for value in result):
        raise ValueError("calendar recurrence datetime cannot be null")
    return [value for value in result if value is not None]


def _strings(values: list[object]) -> list[str]:
    if not all(isinstance(value, str) for value in values):
        raise ValueError("invalid stored calendar strings")
    return [value for value in values if isinstance(value, str)]


def _string(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise ValueError(f"invalid stored calendar {key}")
    return result


def _optional_string(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("invalid optional calendar string")
    return value


def _integer(value: dict[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool):
        raise ValueError(f"invalid stored calendar {key}")
    return result


def _boolean(value: dict[str, object], key: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        raise ValueError(f"invalid stored calendar {key}")
    return result
