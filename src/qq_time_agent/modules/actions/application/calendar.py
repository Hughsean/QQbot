"""Actions-owned execution of Calendar System mutations."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.actions.application.ports import ActionRepository
from qq_time_agent.modules.actions.contracts import ActionResultView
from qq_time_agent.modules.actions.domain.models import ActionRequest, ActionStatus, ActionType
from qq_time_agent.modules.agenda.contracts import (
    AgendaCommandPort,
    AgendaDraft,
    AgendaEntryView,
    AgendaQueryPort,
)
from qq_time_agent.modules.audit.contracts import AuditEvent, AuditPort
from qq_time_agent.modules.reminders.contracts import ReminderCommandPort


class CalendarActionExecutor:
    def __init__(
        self,
        repository: ActionRepository,
        agenda: AgendaCommandPort,
        agenda_query: AgendaQueryPort,
        reminders: ReminderCommandPort,
        clock: Clock,
        audit: AuditPort | None,
    ) -> None:
        self._repository = repository
        self._agenda = agenda
        self._query = agenda_query
        self._reminders = reminders
        self._clock = clock
        self._audit = audit

    async def execute(
        self,
        user_id: str,
        operation: str,
        payload: Mapping[str, object],
        idempotency_key: str,
    ) -> ActionResultView:
        action = await self._repository.add(
            ActionRequest.calendar_operation(
                user_id, _action_type(operation), idempotency_key, payload, self._clock.now()
            )
        )
        if action.status is ActionStatus.SUCCEEDED:
            return _result(action)
        action.start()
        await self._repository.save(action)
        try:
            result = await self._dispatch(action)
        except (PermissionError, LookupError, ValueError):
            await self._fail(action, "PolicyRejected", "REJECTED")
            raise
        except Exception as exc:
            await self._fail(action, type(exc).__name__, "FAILED")
            raise
        action.succeed(
            _required(result.agenda_entry_id),
            _required(result.agenda_entry_version),
            result.reminder_id,
        )
        await self._repository.save(action)
        await self._audit_action(action, "SUCCEEDED")
        return _result(action)

    async def _dispatch(self, action: ActionRequest) -> ActionResultView:
        handlers = {
            ActionType.CREATE_AGENDA: self._create,
            ActionType.UPDATE_AGENDA: self._update,
            ActionType.COMPLETE_AGENDA: self._complete,
            ActionType.CANCEL_AGENDA: self._cancel,
            ActionType.UPDATE_REMINDER: self._update_reminder,
        }
        return await handlers[action.action_type](action)

    async def _create(self, action: ActionRequest) -> ActionResultView:
        draft = _draft(action.operation_payload or {})
        if await self._query.get_busy_intervals(draft.starts_at, draft.ends_at):
            raise ValueError("agenda interval conflicts with an active entry")
        entry = await self._agenda.create_entry(action.action_id, draft, action.idempotency_key)
        reminder = await self._schedule(action, entry.agenda_entry_id, entry.version, draft)
        return _view(action, entry.agenda_entry_id, entry.version, reminder)

    async def _update(self, action: ActionRequest) -> ActionResultView:
        entry_id, expected, current = await self._target(action)
        draft = _draft(action.operation_payload or {}, current)
        conflicts = await self._query.get_busy_intervals(draft.starts_at, draft.ends_at)
        if any(item.agenda_entry_id != entry_id for item in conflicts):
            raise ValueError("agenda interval conflicts with an active entry")
        revised = await self._agenda.revise_entry(
            action.action_id, entry_id, expected, draft, action.idempotency_key
        )
        await self._reminders.cancel_for_entry(entry_id, expected)
        reminder = await self._schedule(action, entry_id, revised.version, draft)
        return _view(action, entry_id, revised.version, reminder)

    async def _complete(self, action: ActionRequest) -> ActionResultView:
        entry_id, expected, _ = await self._target(action)
        revised = await self._agenda.complete_entry(entry_id, expected, action.idempotency_key)
        await self._reminders.cancel_for_entry(entry_id, expected)
        return _view(action, entry_id, revised.version)

    async def _cancel(self, action: ActionRequest) -> ActionResultView:
        entry_id, expected, _ = await self._target(action)
        revised = await self._agenda.cancel_entry(
            action.action_id, entry_id, expected, action.idempotency_key
        )
        await self._reminders.cancel_for_entry(entry_id, expected)
        return _view(action, entry_id, revised.version)

    async def _update_reminder(self, action: ActionRequest) -> ActionResultView:
        entry_id, expected, entry = await self._target(action)
        payload = action.operation_payload or {}
        reminder_id = _required(action.reminder_id)
        expected_occurrence = _integer(payload, "expected_occurrence", 1)
        due_at = _time(payload, "due_at")
        if due_at > entry.starts_at:
            raise ValueError("reminder due_at must not be after agenda start")
        values = await self._reminders.list_for_entry(entry_id)
        current = next(
            (
                item
                for item in values
                if item.reminder_id == reminder_id
                and item.agenda_entry_version == expected
                and item.occurrence == expected_occurrence
                and item.status not in {"CANCELLED", "DEAD_LETTER", "SENT"}
            ),
            None,
        )
        if current is None:
            raise LookupError("reminder target is stale or does not exist")
        updated = await self._reminders.reschedule(reminder_id, due_at, self._clock.now())
        return _view(action, entry_id, expected, updated.reminder_id)

    async def _target(self, action: ActionRequest) -> tuple[UUID, int, AgendaEntryView]:
        entry_id = _required(action.agenda_entry_id)
        expected = _required(action.agenda_entry_version)
        entry = await self._query.get_entry(entry_id)
        if entry is None or entry.status != "ACTIVE":
            raise LookupError("active agenda entry does not exist")
        if entry.version != expected:
            raise ValueError("agenda entry version is stale")
        return entry_id, expected, entry

    async def _schedule(
        self, action: ActionRequest, entry_id: UUID, version: int, draft: AgendaDraft
    ) -> UUID:
        payload = action.operation_payload or {}
        explicit_due = payload.get("reminder_due_at")
        due_at = (
            _time(payload, "reminder_due_at")
            if explicit_due is not None
            else draft.starts_at - timedelta(minutes=_integer(payload, "reminder_lead_minutes", 30))
        )
        if due_at > draft.starts_at:
            raise ValueError("reminder due_at must not be after agenda start")
        reminder = await self._reminders.schedule(
            entry_id,
            version,
            due_at,
            f"{action.idempotency_key}:reminder:v{version}",
        )
        return reminder.reminder_id

    async def _fail(self, action: ActionRequest, failure: str, outcome: str) -> None:
        action.fail(failure)
        await self._repository.save(action)
        await self._audit_action(action, outcome)

    async def _audit_action(self, action: ActionRequest, outcome: str) -> None:
        if self._audit is not None:
            await self._audit.append(
                AuditEvent(
                    "action-executed",
                    action.user_id,
                    f"action:{action.action_id}",
                    outcome,
                    self._clock.now(),
                    {"action_type": action.action_type.value},
                )
            )


def _action_type(value: str) -> ActionType:
    try:
        return ActionType(value)
    except ValueError as exc:
        raise ValueError("unsupported calendar operation") from exc


def _draft(payload: Mapping[str, object], current: AgendaEntryView | None = None) -> AgendaDraft:
    title = _string(payload, "title", None if current is None else current.title)
    timezone = _string(payload, "timezone", None if current is None else current.timezone)
    kind = _string(payload, "kind", "EVENT" if current is None else current.kind)
    starts = _time(payload, "starts_at", None if current is None else current.starts_at)
    ends = _time(payload, "ends_at", None if current is None else current.ends_at)
    if kind not in {"EVENT", "TASK_BLOCK"} or ends <= starts:
        raise ValueError("calendar draft interval is invalid")
    refs = _refs(payload, () if current is None else current.source_refs)
    proposal_id = UUID(int=0) if current is None else current.proposal_id
    return AgendaDraft(kind, title, starts, ends, timezone, refs, proposal_id)


def _string(payload: Mapping[str, object], key: str, fallback: str | None) -> str:
    value = payload.get(key, fallback)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _time(payload: Mapping[str, object], key: str, fallback: datetime | None = None) -> datetime:
    value = payload.get(key, fallback)
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value)
    else:
        raise ValueError(f"{key} is required")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{key} must include timezone")
    return result


def _integer(payload: Mapping[str, object], key: str, fallback: int) -> int:
    value = payload.get(key, fallback)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be non-negative")
    return value


def _refs(payload: Mapping[str, object], fallback: tuple[str, ...]) -> tuple[str, ...]:
    value = payload.get("source_refs", fallback)
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError("source_refs are invalid")
    return tuple(value)


def _required[T](value: T | None) -> T:
    if value is None:
        raise ValueError("calendar action result is incomplete")
    return value


def _view(
    action: ActionRequest, entry_id: UUID, version: int, reminder_id: UUID | None = None
) -> ActionResultView:
    return ActionResultView(
        action.action_id, action.action_type.value, "SUCCEEDED", entry_id, version, reminder_id
    )


def _result(action: ActionRequest) -> ActionResultView:
    return ActionResultView(
        action.action_id,
        action.action_type.value,
        action.status.value,
        action.agenda_entry_id,
        action.agenda_entry_version,
        action.reminder_id,
    )
