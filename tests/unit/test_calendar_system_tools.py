from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.contracts.tools import ToolCallContext
from qq_time_agent.modules.actions.contracts import ActionResultView
from qq_time_agent.modules.agenda.contracts import AgendaEntryView, BusyInterval
from qq_time_agent.modules.calendar_system.application.authorization import (
    OwnerCalendarAuthorization,
)
from qq_time_agent.modules.calendar_system.application.tools import CalendarToolRegistry

NOW = datetime(2026, 8, 26, 9, tzinfo=UTC)
ENTRY_ID = uuid4()


@dataclass
class Agenda:
    entry: AgendaEntryView
    updates: list[tuple[UUID, int]]

    async def get_entry(self, entry_id: UUID) -> AgendaEntryView | None:
        return self.entry if entry_id == self.entry.agenda_entry_id else None

    async def list_active(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaEntryView, ...]:
        return (
            (self.entry,)
            if self.entry.starts_at < range_end and self.entry.ends_at > range_start
            else ()
        )

    async def find_active_by_title(self, title: str) -> tuple[AgendaEntryView, ...]:
        return (self.entry,) if title == self.entry.title else ()

    async def get_busy_intervals(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[BusyInterval, ...]:
        del range_start, range_end
        return ()


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


@dataclass
class CapturingActions:
    payload: Mapping[str, object] | None = None
    operation: str | None = None

    async def execute_calendar_operation(
        self,
        user_id: str,
        operation: str,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> ActionResultView:
        del user_id, idempotency_key
        self.payload = payload
        self.operation = operation
        return ActionResultView(uuid4(), "CREATE_AGENDA", "SUCCEEDED", ENTRY_ID, 1, uuid4())


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
    registry = CalendarToolRegistry(agenda, Actions(), OwnerCalendarAuthorization("owner"))
    with pytest.raises(PermissionError):
        await registry.call("other", "get_agenda", {"agenda_entry_id": str(ENTRY_ID)})
    with pytest.raises(ValueError, match="stale"):
        await registry.call(
            "owner",
            "update_agenda",
            {"agenda_entry_id": str(ENTRY_ID), "expected_version": 1},
        )


@pytest.mark.asyncio
async def test_calendar_time_with_offset_keeps_its_absolute_instant() -> None:
    actions = CapturingActions()
    registry = CalendarToolRegistry(
        Agenda(_entry(), []), actions, OwnerCalendarAuthorization("owner"), "Asia/Shanghai"
    )
    await registry.call(
        "owner",
        "create_agenda",
        {
            "title": "北京时间会议",
            "starts_at": "2026-08-27T09:00:00Z",
            "ends_at": "2026-08-27T10:00:00Z",
            "timezone": "Asia/Shanghai",
            "kind": "EVENT",
        },
    )
    assert actions.payload is not None
    assert actions.payload["starts_at"] == "2026-08-27T17:00:00+08:00"


@pytest.mark.asyncio
async def test_calendar_time_without_offset_is_rejected() -> None:
    actions = CapturingActions()
    registry = CalendarToolRegistry(
        Agenda(_entry(), []), actions, OwnerCalendarAuthorization("owner"), "Asia/Shanghai"
    )
    with pytest.raises(ValueError, match="timezone offset"):
        await registry.call(
            "owner",
            "create_agenda",
            {
                "title": "北京时间会议",
                "starts_at": "2026-08-27T09:00:00",
                "ends_at": "2026-08-27T10:00:00",
                "timezone": "Asia/Shanghai",
                "kind": "EVENT",
            },
        )
    assert actions.payload is None


@pytest.mark.asyncio
async def test_calendar_reads_are_displayed_in_owner_timezone() -> None:
    registry = CalendarToolRegistry(
        Agenda(_entry(), []), Actions(), OwnerCalendarAuthorization("owner"), "Asia/Shanghai"
    )
    value = await registry.call("owner", "get_agenda", {"agenda_entry_id": str(ENTRY_ID)})
    assert isinstance(value, dict)
    assert value["starts_at"] == "2026-08-26T17:00:00+08:00"
    assert value["timezone"] == "Asia/Shanghai"
    assert value["calendar_timezone"] == "UTC"


@pytest.mark.asyncio
async def test_calendar_list_returns_authoritative_active_range() -> None:
    registry = CalendarToolRegistry(
        Agenda(_entry(), []), Actions(), OwnerCalendarAuthorization("owner"), "Asia/Shanghai"
    )

    value = await registry.call(
        "owner",
        "list_agenda",
        {
            "range_start": "2026-08-26T08:00:00+08:00",
            "range_end": "2026-08-27T08:00:00+08:00",
            "timezone": "Asia/Shanghai",
        },
    )

    assert isinstance(value, dict)
    assert value["status"] == "SUCCEEDED" and value["count"] == 1
    assert value["items"][0]["title"] == "项目会议"


@pytest.mark.asyncio
async def test_create_receipt_contains_user_visible_schedule_facts() -> None:
    actions = CapturingActions()
    registry = CalendarToolRegistry(
        Agenda(_entry(), []), actions, OwnerCalendarAuthorization("owner"), "Asia/Shanghai"
    )

    value = await registry.call(
        "owner",
        "create_agenda",
        {
            "title": "南瑞继保测评",
            "starts_at": "2026-09-12T18:00:00+08:00",
            "ends_at": "2026-09-12T19:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "kind": "EVENT",
            "reminder_due_at": "2026-09-12T18:00:00+08:00",
        },
    )

    assert isinstance(value, dict)
    assert value["title"] == "南瑞继保测评"
    assert value["reminder_due_at"] == "2026-09-12T18:00:00+08:00"


@pytest.mark.asyncio
async def test_create_uses_configured_default_reminder_and_all_turn_sources() -> None:
    actions = CapturingActions()
    registry = CalendarToolRegistry(
        Agenda(_entry(), []),
        actions,
        OwnerCalendarAuthorization("owner"),
        "Asia/Shanghai",
        default_reminder_minutes=20,
    )
    command_id, evidence_id = uuid4(), uuid4()

    value = await registry.call(
        "owner",
        "create_agenda",
        {
            "title": "集中大课",
            "starts_at": "2026-09-16T14:30:00+08:00",
            "ends_at": "2026-09-16T15:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "kind": "EVENT",
        },
        ToolCallContext(
            "QQ_DIRECT",
            command_id,
            (f"inbox:{evidence_id}",),
        ),
    )

    assert actions.payload is not None
    assert actions.payload["reminder_lead_minutes"] == 20
    assert actions.payload["source_refs"] == [
        f"inbox:{evidence_id}",
        f"inbox:{command_id}",
    ]
    assert value["reminder_due_at"] == "2026-09-16T14:10:00+08:00"


@pytest.mark.asyncio
async def test_reminder_update_uses_owner_timezone_normalization() -> None:
    actions = CapturingActions()
    registry = CalendarToolRegistry(
        Agenda(_entry(), []), actions, OwnerCalendarAuthorization("owner"), "Asia/Shanghai"
    )
    await registry.call(
        "owner",
        "update_reminder",
        {
            "agenda_entry_id": str(ENTRY_ID),
            "expected_version": 2,
            "reminder_id": str(uuid4()),
            "expected_occurrence": 1,
            "due_at": "2026-08-26T00:00:00Z",
        },
    )
    assert actions.operation == "UPDATE_REMINDER"
    assert actions.payload is not None
    assert actions.payload["due_at"] == "2026-08-26T08:00:00+08:00"
