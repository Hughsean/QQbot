"""Safe tool facade for the independent calendar system."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agenda.contracts import (
    AgendaCommandPort,
    AgendaDraft,
    AgendaEntryView,
    AgendaQueryPort,
)
from qq_time_agent.modules.agent.contracts import AgentToolDefinition
from qq_time_agent.modules.reminders.contracts import ReminderCommandPort


class CalendarToolRegistry:
    def __init__(
        self,
        agenda_query: AgendaQueryPort,
        agenda_commands: AgendaCommandPort,
        reminders: ReminderCommandPort,
        clock: Clock,
    ) -> None:
        self._agenda_query = agenda_query
        self._agenda_commands = agenda_commands
        self._reminders = reminders
        self._clock = clock
        self._definitions = (
            AgentToolDefinition(
                "find_agenda_candidates",
                "Find active agenda entries by exact title for target resolution.",
                {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
            ),
            AgentToolDefinition(
                "get_agenda",
                "Read one active agenda entry by id.",
                {
                    "type": "object",
                    "properties": {"agenda_entry_id": {"type": "string"}},
                    "required": ["agenda_entry_id"],
                },
            ),
            AgentToolDefinition(
                "create_agenda",
                "Create an agenda entry when the requested interval is valid and conflict-free.",
                {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "starts_at": {"type": "string", "format": "date-time"},
                        "ends_at": {"type": "string", "format": "date-time"},
                        "timezone": {"type": "string"},
                        "kind": {"type": "string", "enum": ["EVENT", "TASK_BLOCK"]},
                    },
                    "required": ["title", "starts_at", "ends_at", "timezone", "kind"],
                },
            ),
            AgentToolDefinition(
                "update_agenda",
                "Update an active agenda entry after strict validation.",
                {
                    "type": "object",
                    "properties": {
                        "agenda_entry_id": {"type": "string"},
                        "expected_version": {"type": "integer", "minimum": 1},
                        "title": {"type": "string"},
                        "starts_at": {"type": "string", "format": "date-time"},
                        "ends_at": {"type": "string", "format": "date-time"},
                    },
                    "required": ["agenda_entry_id", "expected_version"],
                },
            ),
            AgentToolDefinition(
                "complete_agenda",
                "Complete an active agenda entry using its current version.",
                {
                    "type": "object",
                    "properties": {
                        "agenda_entry_id": {"type": "string"},
                        "expected_version": {"type": "integer", "minimum": 1},
                    },
                    "required": ["agenda_entry_id", "expected_version"],
                },
            ),
            AgentToolDefinition(
                "cancel_agenda",
                "Cancel an active agenda entry using its current version.",
                {
                    "type": "object",
                    "properties": {
                        "agenda_entry_id": {"type": "string"},
                        "expected_version": {"type": "integer", "minimum": 1},
                    },
                    "required": ["agenda_entry_id", "expected_version"],
                },
            ),
            AgentToolDefinition(
                "update_reminder",
                "Update the earliest active reminder for an agenda entry.",
                {
                    "type": "object",
                    "properties": {
                        "agenda_entry_id": {"type": "string"},
                        "expected_version": {"type": "integer", "minimum": 1},
                        "due_at": {"type": "string", "format": "date-time"},
                    },
                    "required": ["agenda_entry_id", "expected_version", "due_at"],
                },
            ),
        )

    def definitions(self) -> tuple[AgentToolDefinition, ...]:
        return self._definitions

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object:
        if owner_id != "owner":
            raise PermissionError("calendar system is owner-scoped")
        if name == "find_agenda_candidates":
            _only(arguments, {"title"})
            title = _text(arguments, "title")
            return tuple(
                _render(entry) for entry in await self._agenda_query.find_active_by_title(title)
            )
        if name == "get_agenda":
            _only(arguments, {"agenda_entry_id"})
            entry = await self._agenda_query.get_entry(_uuid(arguments, "agenda_entry_id"))
            if entry is None or entry.status != "ACTIVE":
                raise LookupError("active agenda entry does not exist")
            return _render(entry)
        if name == "create_agenda":
            _only(arguments, {"title", "starts_at", "ends_at", "timezone", "kind"})
            return await self._create_agenda(arguments)
        if name == "update_agenda":
            _only(
                arguments,
                {"agenda_entry_id", "expected_version", "title", "starts_at", "ends_at"},
            )
            return await self._update_agenda(arguments)
        if name == "complete_agenda":
            _only(arguments, {"agenda_entry_id", "expected_version"})
            return await self._complete_agenda(arguments)
        if name == "cancel_agenda":
            _only(arguments, {"agenda_entry_id", "expected_version"})
            return await self._cancel_agenda(arguments)
        if name == "update_reminder":
            _only(arguments, {"agenda_entry_id", "expected_version", "due_at"})
            return await self._update_reminder(arguments)
        raise ValueError("unknown calendar tool")

    async def _create_agenda(self, arguments: Mapping[str, object]) -> object:
        title = _text(arguments, "title")
        kind = _text(arguments, "kind")
        timezone = _text(arguments, "timezone")
        starts = _moment(arguments.get("starts_at"), None)
        ends = _moment(arguments.get("ends_at"), None)
        if kind not in {"EVENT", "TASK_BLOCK"} or ends <= starts:
            raise ValueError("agenda creation is invalid")
        if await self._agenda_query.get_busy_intervals(starts, ends):
            raise ValueError("agenda interval conflicts with an active entry")
        draft = AgendaDraft(kind, title, starts, ends, timezone, ("agent:owner",), uuid4())
        result = await self._agenda_commands.create_entry(
            uuid4(), draft, f"agent:agenda:create:{starts.isoformat()}:{title}"
        )
        return {
            "status": "CREATED",
            "agenda_entry_id": str(result.agenda_entry_id),
            "version": result.version,
        }

    async def _update_agenda(self, arguments: Mapping[str, object]) -> object:
        entry_id = _uuid(arguments, "agenda_entry_id")
        expected = _positive_int(arguments, "expected_version")
        entry = await self._agenda_query.get_entry(entry_id)
        if entry is None or entry.status != "ACTIVE":
            raise LookupError("active agenda entry does not exist")
        if entry.version != expected:
            raise ValueError("agenda entry version is stale")
        title = arguments.get("title", entry.title)
        starts = _moment(arguments.get("starts_at"), entry.starts_at)
        ends = _moment(arguments.get("ends_at"), entry.ends_at)
        if not isinstance(title, str) or not title.strip() or ends <= starts:
            raise ValueError("agenda update is invalid")
        draft = AgendaDraft(
            entry.kind,
            title.strip(),
            starts,
            ends,
            entry.timezone,
            entry.source_refs,
            entry.proposal_id,
        )
        result = await self._agenda_commands.revise_entry(
            uuid4(), entry_id, expected, draft, f"agent:agenda:{entry_id}:v{expected}:update"
        )
        return {
            "status": "UPDATED",
            "agenda_entry_id": str(result.agenda_entry_id),
            "version": result.version,
        }

    async def _update_reminder(self, arguments: Mapping[str, object]) -> object:
        entry_id = _uuid(arguments, "agenda_entry_id")
        expected = _positive_int(arguments, "expected_version")
        entry = await self._agenda_query.get_entry(entry_id)
        if entry is None or entry.status != "ACTIVE":
            raise LookupError("active agenda entry does not exist")
        if entry.version != expected:
            raise ValueError("agenda entry version is stale")
        due_at = _moment(arguments.get("due_at"), None)
        reminders = await self._reminders.list_for_entry(entry_id)
        active = [
            value
            for value in reminders
            if value.status not in {"CANCELLED", "DEAD_LETTER"}
            and value.agenda_entry_version == expected
        ]
        if not active:
            raise LookupError("active reminder does not exist")
        current = min(active, key=lambda value: value.due_at)
        updated = await self._reminders.reschedule(current.reminder_id, due_at, self._clock.now())
        return {
            "status": "UPDATED",
            "reminder_id": str(updated.reminder_id),
            "due_at": updated.due_at.isoformat(),
        }

    async def _complete_agenda(self, arguments: Mapping[str, object]) -> object:
        entry_id, expected, _entry = await self._current_entry(arguments)
        result = await self._agenda_commands.complete_entry(
            entry_id, expected, f"agent:agenda:{entry_id}:v{expected}:complete"
        )
        await self._reminders.cancel_for_entry(entry_id, expected)
        return {
            "status": "COMPLETED",
            "agenda_entry_id": str(result.agenda_entry_id),
            "version": result.version,
        }

    async def _cancel_agenda(self, arguments: Mapping[str, object]) -> object:
        entry_id, expected, _entry = await self._current_entry(arguments)
        result = await self._agenda_commands.cancel_entry(
            uuid4(),
            entry_id,
            expected,
            f"agent:agenda:{entry_id}:v{expected}:cancel",
        )
        await self._reminders.cancel_for_entry(entry_id, expected)
        return {
            "status": "CANCELLED",
            "agenda_entry_id": str(result.agenda_entry_id),
            "version": result.version,
        }

    async def _current_entry(
        self, arguments: Mapping[str, object]
    ) -> tuple[UUID, int, AgendaEntryView]:
        entry_id = _uuid(arguments, "agenda_entry_id")
        expected = _positive_int(arguments, "expected_version")
        entry = await self._agenda_query.get_entry(entry_id)
        if entry is None or entry.status != "ACTIVE":
            raise LookupError("active agenda entry does not exist")
        if entry.version != expected:
            raise ValueError("agenda entry version is stale")
        return entry_id, expected, entry


def _text(arguments: Mapping[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _only(arguments: Mapping[str, object], allowed: set[str]) -> None:
    unknown = set(arguments) - allowed
    if unknown:
        raise ValueError(f"unknown calendar arguments: {', '.join(sorted(unknown))}")


def _uuid(arguments: Mapping[str, object], key: str) -> UUID:
    try:
        return UUID(_text(arguments, key))
    except ValueError as exc:
        raise ValueError(f"{key} must be a UUID") from exc


def _positive_int(arguments: Mapping[str, object], key: str) -> int:
    value = arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} must be positive")
    return value


def _moment(value: object, fallback: datetime | None) -> datetime:
    if value is None and fallback is not None:
        return fallback
    if not isinstance(value, str):
        raise ValueError("calendar time is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("calendar time must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("calendar time must include timezone")
    return parsed


def _render(entry: AgendaEntryView) -> dict[str, object]:
    return {
        "agenda_entry_id": str(entry.agenda_entry_id),
        "title": entry.title,
        "starts_at": entry.starts_at.isoformat(),
        "ends_at": entry.ends_at.isoformat(),
        "timezone": entry.timezone,
        "version": entry.version,
        "status": entry.status,
    }
