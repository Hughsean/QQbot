import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.actions.contracts import CompleteAgendaResult
from qq_time_agent.modules.agenda.contracts import AgendaEntryView, BusyInterval
from qq_time_agent.modules.connections.contracts import TaskAccessGrant
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.task_projection.application.completion import (
    ReminderCompletionGate,
    TaskCompletionCoordinator,
)
from qq_time_agent.modules.task_projection.application.completion_sync import (
    TaskCompletionSyncError,
    TaskCompletionSyncService,
)
from qq_time_agent.modules.task_projection.contracts import (
    ExternalTaskChange,
    ExternalTaskDeltaPage,
    ExternalTaskView,
    ReminderCompletionOutcome,
)
from qq_time_agent.modules.task_projection.domain import (
    TaskProjectionCursor,
    TaskProjectionMapping,
    TaskProjectionTarget,
)

NOW = datetime(2026, 9, 13, tzinfo=UTC)


@dataclass
class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Targets:
    target: TaskProjectionTarget

    async def get_for_connection(self, connection_id: UUID) -> TaskProjectionTarget | None:
        return self.target if connection_id == self.target.connection_id else None

    async def list_ready(self, user_id: str) -> tuple[TaskProjectionTarget, ...]:
        return (self.target,) if user_id == self.target.user_id else ()


@dataclass
class Mappings:
    mapping: TaskProjectionMapping | None
    save_error: bool = False

    async def list_for_agenda(self, agenda_entry_id: UUID) -> tuple[TaskProjectionMapping, ...]:
        return (
            (self.mapping,)
            if self.mapping is not None and self.mapping.agenda_entry_id == agenda_entry_id
            else ()
        )

    async def get_for_external_task(
        self, connection_id: UUID, provider_list_ref: str, provider_task_ref: str
    ) -> TaskProjectionMapping | None:
        value = self.mapping
        if (
            value is not None
            and value.connection_id == connection_id
            and value.provider_list_ref == provider_list_ref
            and value.provider_task_ref == provider_task_ref
        ):
            return value
        return None

    async def save(self, mapping: TaskProjectionMapping, expected_version: int) -> None:
        del mapping, expected_version
        if self.save_error:
            raise RuntimeError("stale")


@dataclass
class Agenda:
    entry: AgendaEntryView

    async def get_entry(self, entry_id: UUID) -> AgendaEntryView | None:
        return self.entry if entry_id == self.entry.agenda_entry_id else None

    async def get_busy_intervals(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[BusyInterval, ...]:
        del range_start, range_end
        return ()

    async def find_active_by_title(self, title: str) -> tuple[AgendaEntryView, ...]:
        return (self.entry,) if title == self.entry.title else ()


@dataclass
class Access:
    connection_id: UUID

    async def acquire_task_access(self, user_id: str, connection_id: UUID) -> TaskAccessGrant:
        assert user_id == "owner" and connection_id == self.connection_id
        return TaskAccessGrant(
            connection_id,
            user_id,
            "account",
            CredentialHandle("token", CredentialKind.ACCESS_TOKEN, None),
        )


@dataclass
class Provider:
    task: ExternalTaskView | None
    delta: ExternalTaskDeltaPage | None = None

    async def get_task(
        self, access_grant: TaskAccessGrant, list_ref: str, task_ref: str
    ) -> ExternalTaskView | None:
        del access_grant, list_ref, task_ref
        return self.task

    async def fetch_delta(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        continuation: str | None,
    ) -> ExternalTaskDeltaPage:
        del access_grant, list_ref, continuation
        if self.delta is None:
            raise AssertionError("delta page was not configured")
        return self.delta


@dataclass
class Cursors:
    value: TaskProjectionCursor | None = None

    async def get(self, connection_id: UUID, provider_list_ref: str) -> TaskProjectionCursor | None:
        del connection_id, provider_list_ref
        return self.value

    async def save(self, cursor: TaskProjectionCursor, expected_version: int | None) -> None:
        del expected_version
        self.value = cursor

    async def delete(self, connection_id: UUID, provider_list_ref: str) -> None:
        del connection_id, provider_list_ref
        self.value = None


@dataclass
class Actions:
    fail: bool = False
    calls: int = 0

    async def complete_agenda(
        self,
        user_id: str,
        entry_id: UUID,
        expected_version: int,
        idempotency_key: str,
    ) -> CompleteAgendaResult:
        del user_id, idempotency_key
        self.calls += 1
        if self.fail:
            raise RuntimeError("synthetic")
        return CompleteAgendaResult(entry_id, expected_version + 1, False)


def _objects(
    *, completed: bool = True, mapping: bool = True
) -> tuple[AgendaEntryView, Targets, Mappings, Provider, Actions]:
    start = NOW + timedelta(hours=1)
    entry = AgendaEntryView(
        uuid4(),
        "TASK_BLOCK",
        "南瑞继保测评",
        start,
        start + timedelta(hours=1),
        "Asia/Shanghai",
        "ACTIVE",
        (),
        uuid4(),
        2,
    )
    connection_id = uuid4()
    target = TaskProjectionTarget.resolve("owner", connection_id, "managed", "小智建议", NOW)
    value = None
    if mapping:
        value = TaskProjectionMapping.pending(
            "owner", entry.agenda_entry_id, entry.version, connection_id, "managed"
        )
        value.activate(entry.version, "task-one", "rev-one", NOW)
    return (
        entry,
        Targets(target),
        Mappings(value),
        Provider(ExternalTaskView("task-one", "rev-two", completed)),
        Actions(),
    )


def _gate(
    entry: AgendaEntryView,
    targets: Targets,
    mappings: Mappings,
    provider: Provider,
    actions: Actions,
    timeout: float = 3.0,
) -> ReminderCompletionGate:
    coordinator = TaskCompletionCoordinator(
        targets,
        mappings,
        Agenda(entry),
        Access(targets.target.connection_id),
        provider,
        actions,
        Clock(),
    )
    return ReminderCompletionGate(mappings, coordinator, timeout)


@pytest.mark.asyncio
async def test_completed_task_invokes_actions_and_suppresses() -> None:
    entry, targets, mappings, provider, actions = _objects()
    result = await _gate(entry, targets, mappings, provider, actions).evaluate_before_delivery(
        "owner", entry.agenda_entry_id, entry.version
    )

    assert result.outcome is ReminderCompletionOutcome.SUPPRESS_COMPLETED
    assert actions.calls == 1
    assert mappings.mapping is not None
    assert mappings.mapping.last_observed_completion is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("completed", "has_mapping", "expected"),
    [
        (False, True, ReminderCompletionOutcome.SEND_NOT_COMPLETED),
        (True, False, ReminderCompletionOutcome.SEND_UNMAPPED),
    ],
)
async def test_unknown_or_unfinished_state_always_sends(
    completed: bool, has_mapping: bool, expected: ReminderCompletionOutcome
) -> None:
    entry, targets, mappings, provider, actions = _objects(completed=completed, mapping=has_mapping)
    result = await _gate(entry, targets, mappings, provider, actions).evaluate_before_delivery(
        "owner", entry.agenda_entry_id, entry.version
    )
    assert result.outcome is expected and not result.suppress
    assert actions.calls == 0


@pytest.mark.asyncio
async def test_action_failure_and_missing_task_cannot_suppress() -> None:
    entry, targets, mappings, provider, actions = _objects()
    actions.fail = True
    failed = await _gate(entry, targets, mappings, provider, actions).evaluate_before_delivery(
        "owner", entry.agenda_entry_id, entry.version
    )
    assert failed.outcome is ReminderCompletionOutcome.SEND_STALE

    entry, targets, mappings, provider, actions = _objects()
    provider.task = None
    missing = await _gate(entry, targets, mappings, provider, actions).evaluate_before_delivery(
        "owner", entry.agenda_entry_id, entry.version
    )
    assert missing.outcome is ReminderCompletionOutcome.SEND_UNAVAILABLE
    assert actions.calls == 0


@pytest.mark.asyncio
async def test_gate_timeout_degrades_to_send() -> None:
    entry, targets, mappings, provider, actions = _objects()
    gate = _gate(entry, targets, mappings, provider, actions, timeout=0.001)

    async def delayed(_: TaskProjectionMapping) -> object:
        await asyncio.sleep(0.02)
        raise AssertionError

    gate._coordinator.verify = delayed  # type: ignore[method-assign]
    result = await gate.evaluate_before_delivery("owner", entry.agenda_entry_id, entry.version)
    assert result.outcome is ReminderCompletionOutcome.SEND_UNAVAILABLE


@pytest.mark.asyncio
async def test_delta_completion_advances_cursor_only_after_verified_action() -> None:
    entry, targets, mappings, provider, actions = _objects()
    provider.delta = ExternalTaskDeltaPage(
        (ExternalTaskChange("task-one", "rev-two", True, False),),
        "https://graph.microsoft.com/delta?opaque=one",
    )
    cursors = Cursors()
    coordinator = TaskCompletionCoordinator(
        targets,
        mappings,
        Agenda(entry),
        Access(targets.target.connection_id),
        provider,
        actions,
        Clock(),
    )
    service = TaskCompletionSyncService(
        targets,
        mappings,
        cursors,
        Access(targets.target.connection_id),
        provider,
        coordinator,
        Clock(),
    )

    assert await service.sync_target(targets.target.connection_id) == 1
    assert cursors.value is not None
    assert cursors.value.opaque_cursor.endswith("opaque=one")

    entry, targets, mappings, provider, actions = _objects()
    provider.delta = ExternalTaskDeltaPage(
        (ExternalTaskChange("task-one", "rev-two", True, False),), "retry-cursor"
    )
    actions.fail = True
    cursors = Cursors()
    coordinator = TaskCompletionCoordinator(
        targets,
        mappings,
        Agenda(entry),
        Access(targets.target.connection_id),
        provider,
        actions,
        Clock(),
    )
    service = TaskCompletionSyncService(
        targets,
        mappings,
        cursors,
        Access(targets.target.connection_id),
        provider,
        coordinator,
        Clock(),
    )
    with pytest.raises(TaskCompletionSyncError, match="TransientProvider"):
        await service.sync_target(targets.target.connection_id)
    assert cursors.value is None
