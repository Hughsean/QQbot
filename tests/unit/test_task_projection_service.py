from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.connections.contracts import TaskAccessGrant
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.task_projection.application import (
    ProjectionOperationError,
    TaskProjectionService,
)
from qq_time_agent.modules.task_projection.contracts import (
    ExternalTaskDraft,
    ExternalTaskList,
    ExternalTaskView,
    TaskProviderError,
)
from qq_time_agent.modules.task_projection.domain.models import (
    TaskProjectionMapping,
    TaskProjectionStatus,
    TaskProjectionTarget,
)

NOW = datetime(2026, 9, 13, 8, tzinfo=UTC)


@dataclass
class Clock:
    def now(self) -> datetime:
        return NOW


@dataclass
class Agenda:
    entry: AgendaEntryView | None

    async def get_entry(self, entry_id: UUID) -> AgendaEntryView | None:
        assert self.entry is None or self.entry.agenda_entry_id == entry_id
        return self.entry


@dataclass
class Targets:
    values: tuple[TaskProjectionTarget, ...]

    async def list_ready(self, user_id: str) -> tuple[TaskProjectionTarget, ...]:
        assert user_id == "owner"
        return self.values


@dataclass
class Mappings:
    values: dict[tuple[UUID, UUID], TaskProjectionMapping] = field(default_factory=dict)

    async def get_for_agenda(
        self, connection_id: UUID, agenda_entry_id: UUID
    ) -> TaskProjectionMapping | None:
        return self.values.get((connection_id, agenda_entry_id))

    async def list_for_agenda(self, agenda_entry_id: UUID) -> tuple[TaskProjectionMapping, ...]:
        return tuple(
            value for (_, entry_id), value in self.values.items() if entry_id == agenda_entry_id
        )

    async def add_or_get(self, mapping: TaskProjectionMapping) -> TaskProjectionMapping:
        return self.values.setdefault((mapping.connection_id, mapping.agenda_entry_id), mapping)

    async def save(self, mapping: TaskProjectionMapping, expected_version: int) -> None:
        assert mapping.version == expected_version + 1
        self.values[(mapping.connection_id, mapping.agenda_entry_id)] = mapping


@dataclass
class Connections:
    async def acquire_task_access(self, user_id: str, connection_id: UUID) -> TaskAccessGrant:
        return TaskAccessGrant(
            connection_id,
            user_id,
            "account",
            CredentialHandle("synthetic-task-access", CredentialKind.ACCESS_TOKEN, None),
        )


@dataclass
class Provider:
    tasks: dict[str, ExternalTaskView] = field(default_factory=dict)
    closes: list[tuple[str, bool]] = field(default_factory=list)
    fail: bool = False

    async def list_task_lists(self, access_grant: TaskAccessGrant) -> tuple[ExternalTaskList, ...]:
        return ()

    async def upsert_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        draft: ExternalTaskDraft,
        task_ref: str | None,
    ) -> ExternalTaskView:
        if self.fail:
            raise TaskProviderError("TransientProvider")
        current = (
            task_ref
            or self.tasks.get(
                draft.stable_marker, ExternalTaskView("task-one", None, False)
            ).task_ref
        )
        result = ExternalTaskView(current, "revision", False)
        self.tasks[draft.stable_marker] = result
        return result

    async def find_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        stable_marker: str,
    ) -> ExternalTaskView | None:
        return self.tasks.get(stable_marker)

    async def close_task(
        self,
        access_grant: TaskAccessGrant,
        list_ref: str,
        task_ref: str,
        completed: bool,
    ) -> None:
        self.closes.append((task_ref, completed))


def _entry(status: str = "ACTIVE", version: int = 1) -> AgendaEntryView:
    return AgendaEntryView(
        uuid4(),
        "TASK_BLOCK",
        "南瑞继保测评",
        NOW,
        NOW + timedelta(hours=1),
        "Asia/Shanghai",
        status,
        ("qq:test",),
        uuid4(),
        version,
    )


def _target() -> TaskProjectionTarget:
    return TaskProjectionTarget.resolve("owner", uuid4(), "managed", "小智建议", NOW)


def _service(
    entry: AgendaEntryView,
    target: TaskProjectionTarget,
    mappings: Mappings,
    provider: Provider,
) -> TaskProjectionService:
    return TaskProjectionService(
        Targets((target,)), mappings, Agenda(entry), Connections(), provider, Clock()
    )


@pytest.mark.asyncio
async def test_active_entry_is_upserted_idempotently_to_same_mapping() -> None:
    entry, target, mappings, provider = _entry(), _target(), Mappings(), Provider()
    service = _service(entry, target, mappings, provider)

    first = await service.project_agenda_entry(entry.agenda_entry_id, 1, "first")
    second = await service.project_agenda_entry(entry.agenda_entry_id, 1, "second")

    mapping = next(iter(mappings.values.values()))
    assert first.outcome == second.outcome == "PROJECTED"
    assert len(provider.tasks) == 1
    assert mapping.provider_task_ref == "task-one"
    assert mapping.status is TaskProjectionStatus.ACTIVE


@pytest.mark.asyncio
async def test_provider_failure_keeps_agenda_unchanged_and_marks_retry() -> None:
    entry, target, mappings = _entry(), _target(), Mappings()
    with pytest.raises(ProjectionOperationError, match="TransientProvider"):
        await _service(entry, target, mappings, Provider(fail=True)).project_agenda_entry(
            entry.agenda_entry_id, 1, "failure"
        )
    assert entry.status == "ACTIVE"
    assert next(iter(mappings.values.values())).status is TaskProjectionStatus.RETRY_WAIT


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "completed"), [("COMPLETED", True), ("CANCELLED", False)])
async def test_terminal_agenda_closes_existing_projection(status: str, completed: bool) -> None:
    active, target, mappings, provider = _entry(), _target(), Mappings(), Provider()
    service = _service(active, target, mappings, provider)
    await service.project_agenda_entry(active.agenda_entry_id, 1, "create")
    terminal = replace(active, status=status, version=2)
    service = _service(terminal, target, mappings, provider)

    result = await service.project_agenda_entry(terminal.agenda_entry_id, 2, "close")

    assert result.outcome == "CLOSED"
    assert provider.closes == [("task-one", completed)]
    assert next(iter(mappings.values.values())).status is TaskProjectionStatus.CLOSED


@pytest.mark.asyncio
async def test_terminal_projection_recovers_task_created_before_local_mapping_save() -> None:
    active, target, mappings, provider = _entry(), _target(), Mappings(), Provider()
    mapping = TaskProjectionMapping.pending(
        "owner", active.agenda_entry_id, 1, target.connection_id, target.provider_list_ref
    )
    await mappings.add_or_get(mapping)
    marker = (
        "qq-time-agent:" + sha256(f"qq-time-agent:{active.agenda_entry_id}".encode()).hexdigest()
    )
    provider.tasks[marker] = ExternalTaskView("recovered-task", "revision", False)
    completed = replace(active, status="COMPLETED", version=2)

    await _service(completed, target, mappings, provider).project_agenda_entry(
        completed.agenda_entry_id, 2, "recover-close"
    )

    assert provider.closes == [("recovered-task", True)]
    assert mapping.status is TaskProjectionStatus.CLOSED


@pytest.mark.asyncio
async def test_stale_event_never_calls_provider() -> None:
    entry, target, mappings, provider = _entry(version=2), _target(), Mappings(), Provider()
    result = await _service(entry, target, mappings, provider).project_agenda_entry(
        entry.agenda_entry_id, 1, "stale"
    )
    assert result.outcome == "STALE"
    assert provider.tasks == {}
    assert mappings.values == {}
