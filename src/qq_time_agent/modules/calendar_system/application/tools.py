"""Safe tool facade for the independent calendar system."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.tools import ToolDefinition
from qq_time_agent.modules.actions.contracts import CalendarActionPort
from qq_time_agent.modules.agenda.contracts import (
    AgendaEntryView,
    AgendaQueryPort,
)
from qq_time_agent.modules.calendar_system.contracts import CalendarAuthorizationPort


class CalendarToolRegistry:
    def __init__(
        self,
        agenda_query: AgendaQueryPort,
        actions: CalendarActionPort,
        authorization: CalendarAuthorizationPort | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._agenda_query = agenda_query
        selected_authorization: CalendarAuthorizationPort
        # The fourth positional argument was historically a Clock. Keep read-only
        # construction usable for downstream callers while production injects the
        # explicit Actions and authorization ports.
        if authorization is not None and not hasattr(authorization, "authorize"):
            self._actions = actions
            selected_authorization = _OwnerAuthorization()
            self._clock = clock
        else:
            self._actions = actions
            selected_authorization = authorization or _OwnerAuthorization()
            self._clock = clock
        self._authorization = selected_authorization
        self._definitions = (
            ToolDefinition(
                "find_agenda_candidates",
                "Find active agenda entries by exact title for target resolution.",
                {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
            ),
            ToolDefinition(
                "get_agenda",
                "Read one active agenda entry by id.",
                {
                    "type": "object",
                    "properties": {"agenda_entry_id": {"type": "string"}},
                    "required": ["agenda_entry_id"],
                },
            ),
            ToolDefinition(
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
            ToolDefinition(
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
            ToolDefinition(
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
            ToolDefinition(
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
            ToolDefinition(
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

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object:
        if not await self._authorization.authorize(owner_id, name):
            raise PermissionError("calendar operation is not authorized")
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
            return await self._create_agenda(owner_id, arguments)
        if name == "update_agenda":
            _only(
                arguments,
                {"agenda_entry_id", "expected_version", "title", "starts_at", "ends_at"},
            )
            return await self._update_agenda(owner_id, arguments)
        if name == "complete_agenda":
            _only(arguments, {"agenda_entry_id", "expected_version"})
            return await self._mutate(owner_id, "COMPLETE_AGENDA", arguments)
        if name == "cancel_agenda":
            _only(arguments, {"agenda_entry_id", "expected_version"})
            return await self._mutate(owner_id, "CANCEL_AGENDA", arguments)
        if name == "update_reminder":
            _only(arguments, {"agenda_entry_id", "expected_version", "due_at"})
            return await self._mutate(owner_id, "UPDATE_REMINDER", arguments)
        raise ValueError("unknown calendar tool")

    async def _create_agenda(self, owner_id: str, arguments: Mapping[str, object]) -> object:
        title = _text(arguments, "title")
        kind = _text(arguments, "kind")
        _text(arguments, "timezone")
        starts = _moment(arguments.get("starts_at"), None)
        ends = _moment(arguments.get("ends_at"), None)
        if kind not in {"EVENT", "TASK_BLOCK"} or ends <= starts:
            raise ValueError("agenda creation is invalid")
        payload = dict(arguments)
        payload["source_refs"] = ["agent:" + owner_id]
        payload["reminder_lead_minutes"] = 30
        return _render_result(
            await self._actions.execute_calendar_operation(
                owner_id,
                "CREATE_AGENDA",
                payload,
                f"agent:agenda:create:{starts.isoformat()}:{title}",
            )
        )

    async def _update_agenda(self, owner_id: str, arguments: Mapping[str, object]) -> object:
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
        payload = dict(arguments)
        payload.update(
            {"starts_at": starts.isoformat(), "ends_at": ends.isoformat(), "title": title.strip()}
        )
        result = await self._actions.execute_calendar_operation(
            owner_id, "UPDATE_AGENDA", payload, f"agent:agenda:{entry_id}:v{expected}:update"
        )
        return _render_result(result)

    async def _update_reminder(self, owner_id: str, arguments: Mapping[str, object]) -> object:
        entry_id = _uuid(arguments, "agenda_entry_id")
        expected = _positive_int(arguments, "expected_version")
        entry = await self._agenda_query.get_entry(entry_id)
        if entry is None or entry.status != "ACTIVE":
            raise LookupError("active agenda entry does not exist")
        if entry.version != expected:
            raise ValueError("agenda entry version is stale")
        payload = dict(arguments)
        payload["due_at"] = _moment(arguments.get("due_at"), None).isoformat()
        return _render_result(
            await self._actions.execute_calendar_operation(
                owner_id,
                "UPDATE_REMINDER",
                payload,
                f"agent:reminder:{entry_id}:v{expected}:{payload['due_at']}",
            )
        )

    async def _complete_agenda(self, arguments: Mapping[str, object]) -> object:
        return await self._mutate("owner", "COMPLETE_AGENDA", arguments)

    async def _cancel_agenda(self, arguments: Mapping[str, object]) -> object:
        return await self._mutate("owner", "CANCEL_AGENDA", arguments)

    async def _mutate(
        self, owner_id: str, operation: str, arguments: Mapping[str, object]
    ) -> object:
        entry_id = _uuid(arguments, "agenda_entry_id")
        expected = _positive_int(arguments, "expected_version")
        await self._current_entry(arguments)
        result = await self._actions.execute_calendar_operation(
            owner_id,
            operation,
            dict(arguments),
            f"agent:agenda:{entry_id}:v{expected}:{operation.casefold()}",
        )
        return _render_result(result)

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


class _OwnerAuthorization:
    async def authorize(self, principal: str, operation: str) -> bool:
        del operation
        return principal == "owner"


def _render_result(value: object) -> dict[str, object]:
    return {
        "status": getattr(value, "status", "SUCCEEDED"),
        "action_id": str(getattr(value, "action_id", "")),
        "agenda_entry_id": str(getattr(value, "agenda_entry_id", ""))
        if getattr(value, "agenda_entry_id", None)
        else None,
        "version": getattr(value, "agenda_entry_version", None),
        "reminder_id": str(getattr(value, "reminder_id", ""))
        if getattr(value, "reminder_id", None)
        else None,
    }


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
