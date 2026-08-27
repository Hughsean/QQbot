"""Business-neutral timezone conversion at application boundaries."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"invalid timezone: {name}") from exc


def localize(value: datetime, timezone: str) -> datetime:
    """Render an aware instant in the requested IANA timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone conversion requires an aware datetime")
    return value.astimezone(resolve_timezone(timezone))


def local_iso(value: datetime, timezone: str, *, timespec: str = "seconds") -> str:
    return localize(value, timezone).isoformat(timespec=timespec)
