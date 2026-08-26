from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.actions.contracts import ActionResultView
from qq_time_agent.modules.agenda.contracts import AgendaEntryView, BusyInterval
from qq_time_agent.modules.calendar_system.application.tools import CalendarToolRegistry

NOW = datetime(2026, 8, 26, 9, tzinfo=UTC)
ENTRY_ID = uuid4()


@dataclass
class Agenda:
    entry: AgendaEntryView
    updates: list[tuple[UUID, int]]

    async def get_entry(self, entry_id: UUID) -> AgendaEntryView | None:
        return self.entry if entry_id == self.entry.agenda_entry_id else None

    async def find_active_by_title(self, title: str) -> tuple[AgendaEntryView, ...]:
        return (self.entry,) if title == self.entry.title else ()

    async def get_busy_intervals(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[BusyInterval, ...]:
        del range_start, range_end
        return ()


@dataclass
@dataclass
class Actions:
    async def execute_calendar_operation(
        self,
        user_id: str,
        operation: str,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> ActionResultView:
        del user_id, operation, payload, idempotency_key
        raise AssertionError("stale version must be rejected before Actions")


def _entry(version: int = 2) -> AgendaEntryView:
    return AgendaEntryView(
        ENTRY_ID,
        "EVENT",
        "项目会议",
        NOW,
        NOW.replace(hour=10),
        "UTC",
        "ACTIVE",
        ("qq:1",),
        uuid4(),
        version,
    )


@pytest.mark.asyncio
async def test_calendar_tool_requires_current_version_and_owner() -> None:
    agenda = Agenda(_entry(), [])
    registry = CalendarToolRegistry(agenda, Actions())
    with pytest.raises(PermissionError):
        await registry.call("other", "get_agenda", {"agenda_entry_id": str(ENTRY_ID)})
    with pytest.raises(ValueError, match="stale"):
        await registry.call(
            "owner",
            "update_agenda",
            {"agenda_entry_id": str(ENTRY_ID), "expected_version": 1},
        )
