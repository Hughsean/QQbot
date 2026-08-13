from dataclasses import dataclass
from datetime import time

import pytest

from qq_time_agent.modules.identity.application.service import UserPreferencesService
from qq_time_agent.modules.identity.contracts import UserPreferencesView


def _preferences() -> UserPreferencesView:
    return UserPreferencesView(
        "owner",
        "Asia/Shanghai",
        time(9),
        time(18),
        time(12),
        time(13, 30),
        (0, 1, 2, 3, 4),
        30,
        60,
    )


@dataclass
class Repository:
    value: UserPreferencesView | None = None
    initializes: int = 0

    async def get(self, user_id: str) -> UserPreferencesView | None:
        return self.value if self.value is not None and self.value.user_id == user_id else None

    async def initialize(self, preferences: UserPreferencesView) -> UserPreferencesView:
        self.initializes += 1
        if self.value is None:
            self.value = preferences
        return self.value


@pytest.mark.asyncio
async def test_preferences_initialize_once_and_reject_other_users() -> None:
    repository = Repository()
    service = UserPreferencesService(repository, _preferences())
    assert await service.get_preferences("owner") == _preferences()
    assert await service.get_preferences("owner") == _preferences()
    assert repository.initializes == 1
    with pytest.raises(LookupError, match="do not exist"):
        await service.get_preferences("other")


@pytest.mark.parametrize(
    "change,message",
    [
        ({"work_start": time(18)}, "working hours"),
        ({"lunch_start": time(8)}, "lunch"),
        ({"working_weekdays": ()}, "weekdays"),
        ({"working_weekdays": (7,)}, "weekdays"),
        ({"working_weekdays": (1, 1)}, "weekdays"),
        ({"timezone": "Mars/Olympus"}, "timezone is invalid"),
        ({"default_task_minutes": 0}, "durations"),
    ],
)
def test_preferences_validate_hard_constraints(change: dict[str, object], message: str) -> None:
    value = _preferences()
    values = {
        "user_id": value.user_id,
        "timezone": value.timezone,
        "work_start": value.work_start,
        "work_end": value.work_end,
        "lunch_start": value.lunch_start,
        "lunch_end": value.lunch_end,
        "working_weekdays": value.working_weekdays,
        "default_event_minutes": value.default_event_minutes,
        "default_task_minutes": value.default_task_minutes,
    }
    values.update(change)
    with pytest.raises(ValueError, match=message):
        UserPreferencesView(**values)  # type: ignore[arg-type]
