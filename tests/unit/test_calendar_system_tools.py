from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaEntryRef, AgendaEntryView
from qq_time_agent.modules.calendar_system.application.tools import CalendarToolRegistry
from qq_time_agent.modules.reminders.contracts import ReminderView

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

    async def revise_entry(
        self,
        action_id: UUID,
        entry_id: UUID,
        expected_version: int,
        draft: object,
        key: str,
    ) -> AgendaEntryRef:
        del action_id, draft, key
        self.updates.append((entry_id, expected_version))
        return AgendaEntryRef(entry_id, expected_version + 1)


@dataclass
class Reminders:
    async def list_for_entry(self, entry_id: UUID) -> tuple[ReminderView, ...]:
        return ()


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return NOW


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
    registry = CalendarToolRegistry(agenda, agenda, Reminders(), FixedClock())
    with pytest.raises(PermissionError):
        await registry.call("other", "get_agenda", {"agenda_entry_id": str(ENTRY_ID)})
    with pytest.raises(ValueError, match="stale"):
        await registry.call(
            "owner",
            "update_agenda",
            {"agenda_entry_id": str(ENTRY_ID), "expected_version": 1},
        )
