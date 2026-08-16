"""Timezone-aware notification quiet-hour policy."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from qq_time_agent.modules.identity.contracts import UserPreferencesView


def next_allowed_at(now: datetime, preferences: UserPreferencesView) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("notification policy time must be timezone-aware")
    if not preferences.quiet_hours_enabled:
        return now
    zone = ZoneInfo(preferences.timezone)
    local = now.astimezone(zone)
    current = local.timetz().replace(tzinfo=None)
    start = preferences.quiet_start
    end = preferences.quiet_end
    if start < end:
        if not start <= current < end:
            return now
        target_day = local.date()
    elif current >= start:
        target_day = local.date() + timedelta(days=1)
    elif current < end:
        target_day = local.date()
    else:
        return now
    return _resolve_local_target(target_day, end, zone, now.astimezone(UTC))


def _resolve_local_target(
    target_day: date, target_time: time, zone: ZoneInfo, now: datetime
) -> datetime:
    wall = datetime.combine(target_day, target_time)
    candidates = tuple(wall.replace(tzinfo=zone, fold=fold).astimezone(UTC) for fold in (0, 1))
    valid = tuple(
        value
        for value in candidates
        if value.astimezone(zone).replace(tzinfo=None) == wall and value > now
    )
    if valid:
        return min(valid)
    normalized = tuple(
        value
        for value in candidates
        if value > now and value.astimezone(zone).replace(tzinfo=None) > wall
    )
    if normalized:
        return min(normalized)
    raise ValueError("quiet-hour end cannot be resolved after current time")
