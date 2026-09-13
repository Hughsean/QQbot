"""Agenda-to-task projection use case with Agenda remaining authoritative."""

from hashlib import sha256
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agenda.contracts import AgendaEntryView, AgendaQueryPort
from qq_time_agent.modules.connections.contracts import TaskAccessError, TaskConnectionAccessPort
from qq_time_agent.modules.task_projection.application.ports import (
    TaskProjectionMappingRepository,
    TaskProjectionTargetRepository,
)
from qq_time_agent.modules.task_projection.contracts import (
    ExternalTaskDraft,
    ProjectionResult,
    TaskProviderError,
    TaskProviderPort,
)
from qq_time_agent.modules.task_projection.domain.models import (
    TaskProjectionMapping,
    TaskProjectionStatus,
    TaskProjectionTarget,
)


class ProjectionOperationError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


class TaskProjectionService:
    def __init__(
        self,
        targets: TaskProjectionTargetRepository,
        mappings: TaskProjectionMappingRepository,
        agenda: AgendaQueryPort,
        connections: TaskConnectionAccessPort,
        provider: TaskProviderPort,
        clock: Clock,
        owner_id: str = "owner",
    ) -> None:
        self._targets = targets
        self._mappings = mappings
        self._agenda = agenda
        self._connections = connections
        self._provider = provider
        self._clock = clock
        self._owner_id = owner_id

    async def project_agenda_entry(
        self, entry_id: UUID, expected_version: int, idempotency_key: str
    ) -> ProjectionResult:
        if expected_version < 1 or not idempotency_key.strip():
            raise ValueError("projection version and idempotency key are required")
        entry = await self._agenda.get_entry(entry_id)
        if entry is None:
            raise ProjectionOperationError("PermanentData")
        if entry.version != expected_version:
            return ProjectionResult(entry_id, entry.version, "STALE", 0)
        if entry.status == "ACTIVE":
            count = await self._upsert_active(entry)
            return ProjectionResult(entry_id, entry.version, "PROJECTED", count)
        count = await self._close_existing(entry)
        return ProjectionResult(entry_id, entry.version, "CLOSED", count)

    async def _upsert_active(self, entry: AgendaEntryView) -> int:
        targets = await self._targets.list_ready(self._owner_id)
        for target in targets:
            await self._upsert_target(entry, target)
        return len(targets)

    async def _upsert_target(self, entry: AgendaEntryView, target: TaskProjectionTarget) -> None:
        mapping = await self._mapping(entry, target)
        try:
            access = await self._connections.acquire_task_access(
                self._owner_id, target.connection_id
            )
            task = await self._provider.upsert_task(
                access,
                target.provider_list_ref,
                _draft(entry),
                mapping.provider_task_ref,
            )
        except (TaskAccessError, TaskProviderError) as exc:
            await self._mark_retry(mapping, entry.version)
            raise ProjectionOperationError(exc.failure_class) from exc
        previous = mapping.version
        mapping.activate(entry.version, task.task_ref, task.revision, self._clock.now())
        await self._mappings.save(mapping, previous)

    async def _mapping(
        self, entry: AgendaEntryView, target: TaskProjectionTarget
    ) -> TaskProjectionMapping:
        current = await self._mappings.get_for_agenda(target.connection_id, entry.agenda_entry_id)
        if current is None:
            return await self._mappings.add_or_get(
                TaskProjectionMapping.pending(
                    self._owner_id,
                    entry.agenda_entry_id,
                    entry.version,
                    target.connection_id,
                    target.provider_list_ref,
                )
            )
        if current.user_id != self._owner_id:
            raise ProjectionOperationError("SecurityPolicy")
        if current.provider_list_ref != target.provider_list_ref:
            previous = current.version
            current.retarget(target.provider_list_ref, entry.version)
            await self._mappings.save(current, previous)
        return current

    async def _close_existing(self, entry: AgendaEntryView) -> int:
        mappings = await self._mappings.list_for_agenda(entry.agenda_entry_id)
        closed = 0
        for mapping in mappings:
            if mapping.status is TaskProjectionStatus.CLOSED:
                continue
            await self._close_mapping(entry, mapping)
            closed += 1
        return closed

    async def _close_mapping(self, entry: AgendaEntryView, mapping: TaskProjectionMapping) -> None:
        try:
            access = await self._connections.acquire_task_access(
                self._owner_id, mapping.connection_id
            )
            task_ref = mapping.provider_task_ref
            if task_ref is None:
                recovered = await self._provider.find_task(
                    access, mapping.provider_list_ref, _draft(entry).stable_marker
                )
                task_ref = None if recovered is None else recovered.task_ref
            if task_ref is not None:
                await self._provider.close_task(
                    access,
                    mapping.provider_list_ref,
                    task_ref,
                    completed=entry.status == "COMPLETED",
                )
        except (TaskAccessError, TaskProviderError) as exc:
            await self._mark_retry(mapping, entry.version)
            raise ProjectionOperationError(exc.failure_class) from exc
        previous = mapping.version
        mapping.close(entry.version, self._clock.now())
        await self._mappings.save(mapping, previous)

    async def _mark_retry(self, mapping: TaskProjectionMapping, agenda_entry_version: int) -> None:
        previous = mapping.version
        mapping.mark_retry(agenda_entry_version)
        await self._mappings.save(mapping, previous)


def _draft(entry: AgendaEntryView) -> ExternalTaskDraft:
    digest = sha256(f"qq-time-agent:{entry.agenda_entry_id}".encode()).hexdigest()
    return ExternalTaskDraft(
        f"qq-time-agent:{digest}",
        entry.title,
        entry.starts_at,
        entry.ends_at,
        entry.timezone,
    )
