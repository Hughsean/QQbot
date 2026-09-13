from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.connections.contracts import TaskAccessGrant
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.task_projection.application.managed_list import (
    ManagedTaskListAmbiguousError,
    ManagedTaskListNotFoundError,
    ManagedTaskListOwnershipError,
    ManagedTaskListService,
)
from qq_time_agent.modules.task_projection.contracts import ExternalTaskList
from qq_time_agent.modules.task_projection.domain.models import (
    TaskProjectionMapping,
    TaskProjectionStatus,
    TaskProjectionTarget,
)

NOW = datetime(2026, 9, 13, 8, tzinfo=UTC)


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return NOW


@dataclass
class MemoryTargetRepository:
    target: TaskProjectionTarget | None = None
    saves: int = 0

    async def get_for_connection(self, connection_id: UUID) -> TaskProjectionTarget | None:
        if self.target is not None and self.target.connection_id == connection_id:
            return self.target
        return None

    async def add_or_get(self, target: TaskProjectionTarget) -> TaskProjectionTarget:
        if self.target is None:
            self.target = target
        return self.target

    async def save(self, target: TaskProjectionTarget, expected_version: int) -> None:
        assert target.version == expected_version + 1
        self.target = target
        self.saves += 1


@dataclass
class FakeConnections:
    calls: list[tuple[str, UUID]] = field(default_factory=list)

    async def acquire_task_access(self, user_id: str, connection_id: UUID) -> TaskAccessGrant:
        self.calls.append((user_id, connection_id))
        return TaskAccessGrant(
            connection_id,
            user_id,
            "account",
            CredentialHandle("synthetic-access", CredentialKind.ACCESS_TOKEN, None),
        )


@dataclass
class FakeProvider:
    values: tuple[ExternalTaskList, ...]

    async def list_task_lists(self, access_grant: TaskAccessGrant) -> tuple[ExternalTaskList, ...]:
        assert access_grant.account_id == "account"
        return self.values


def _list(
    list_ref: str = "managed-list",
    name: str = "小智建议",
    *,
    owner: bool = True,
    shared: bool = False,
) -> ExternalTaskList:
    return ExternalTaskList(list_ref, name, owner, shared, "none")


@pytest.mark.asyncio
async def test_resolve_managed_list_is_exact_owner_bound_and_idempotent() -> None:
    repository = MemoryTargetRepository()
    connections = FakeConnections()
    connection_id = uuid4()
    service = ManagedTaskListService(
        repository,
        connections,
        FakeProvider((_list(name="  小智建议  "), _list("other", "Tasks"))),
        FixedClock(),
    )

    first = await service.resolve("owner", connection_id)
    second = await service.resolve("owner", connection_id)

    assert first.target_id == second.target_id
    assert first.display_name.strip() == "小智建议"
    assert first.status == "READY"
    assert repository.saves == 0
    assert connections.calls == [("owner", connection_id), ("owner", connection_id)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("values", "error"),
    [
        ((), ManagedTaskListNotFoundError),
        ((_list(), _list("duplicate")), ManagedTaskListAmbiguousError),
        ((_list(owner=False),), ManagedTaskListOwnershipError),
        ((_list(shared=True),), ManagedTaskListOwnershipError),
    ],
)
async def test_resolve_rejects_missing_ambiguous_or_non_private_list(
    values: tuple[ExternalTaskList, ...], error: type[RuntimeError]
) -> None:
    service = ManagedTaskListService(
        MemoryTargetRepository(), FakeConnections(), FakeProvider(values), FixedClock()
    )
    with pytest.raises(error):
        await service.resolve("owner", uuid4())


def test_projection_mapping_state_does_not_treat_detach_as_completion() -> None:
    mapping = TaskProjectionMapping.pending("owner", uuid4(), 1, uuid4(), "managed-list")
    mapping.activate("task-one", "revision-one", NOW)
    assert mapping.status is TaskProjectionStatus.ACTIVE
    assert mapping.last_observed_completion is None

    mapping.detach()
    assert mapping.status is TaskProjectionStatus.DETACHED
    assert mapping.last_observed_completion is None

    mapping.close()
    assert mapping.status is TaskProjectionStatus.CLOSED
    with pytest.raises(ValueError, match="terminal"):
        mapping.detach()
