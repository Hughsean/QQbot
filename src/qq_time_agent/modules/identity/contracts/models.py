"""Provider-neutral single-owner preference contract."""

from dataclasses import dataclass
from datetime import time
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class UserPreferencesView:
    user_id: str
    timezone: str
    work_start: time
    work_end: time
    lunch_start: time
    lunch_end: time
    working_weekdays: tuple[int, ...]
    default_event_minutes: int
    default_task_minutes: int
    digest_enabled: bool = True
    digest_local_time: time = time(8, 0)
    conflict_notifications_enabled: bool = True
    reauth_notifications_enabled: bool = True
    quiet_hours_enabled: bool = True
    quiet_start: time = time(22, 0)
    quiet_end: time = time(7, 0)

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.timezone.strip():
            raise ValueError("owner identity and timezone are required")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("owner timezone is invalid") from exc
        if not self.work_start < self.work_end:
            raise ValueError("working hours must be ordered")
        if not self.work_start <= self.lunch_start < self.lunch_end <= self.work_end:
            raise ValueError("lunch must be inside working hours")
        if (
            not self.working_weekdays
            or len(set(self.working_weekdays)) != len(self.working_weekdays)
            or any(day < 0 or day > 6 for day in self.working_weekdays)
        ):
            raise ValueError("working weekdays must use values from 0 to 6")
        if self.default_event_minutes < 1 or self.default_task_minutes < 1:
            raise ValueError("default durations must be positive")
        if self.quiet_hours_enabled and self.quiet_start == self.quiet_end:
            raise ValueError("quiet hours must have a non-zero window")


class UserPreferencesPort(Protocol):
    async def get_preferences(self, user_id: str) -> UserPreferencesView: ...
