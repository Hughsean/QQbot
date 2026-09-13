"""Verified Microsoft task completion and reminder delivery gate."""

import asyncio
from hashlib import sha256
from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.actions.contracts import AgendaCompletionPort
from qq_time_agent.modules.agenda.contracts import AgendaQueryPort
from qq_time_agent.modules.connections.contracts import TaskAccessError, TaskConnectionAccessPort
from qq_time_agent.modules.task_projection.application.ports import (
    TaskProjectionMappingRepository,
    TaskProjectionTargetRepository,
)
from qq_time_agent.modules.task_projection.contracts import (
    ReminderCompletionDecision,
    ReminderCompletionOutcome,
    TaskProviderError,
    TaskProviderPort,
)
from qq_time_agent.modules.task_projection.domain import (
    TaskProjectionMapping,
    TaskProjectionStatus,
    TaskProjectionTargetStatus,
)


class TaskCompletionCoordinator:
    def __init__(
        self,
        targets: TaskProjectionTargetRepository,
        mappings: TaskProjectionMappingRepository,
        agenda: AgendaQueryPort,
        connections: TaskConnectionAccessPort,
        provider: TaskProviderPort,
        actions: AgendaCompletionPort,
        clock: Clock,
    ) -> None:
        self._targets = targets
        self._mappings = mappings
        self._agenda = agenda
        self._connections = connections
        self._provider = provider
        self._actions = actions
        self._clock = clock

    async def verify(self, mapping: TaskProjectionMapping) -> ReminderCompletionDecision:
        stale = await self._validate_mapping(mapping)
        if stale is not None:
            return stale
        task_ref = mapping.provider_task_ref
        if task_ref is None:
            return _decision(ReminderCompletionOutcome.SEND_UNMAPPED, "missing_task_reference")
        try:
            access = await self._connections.acquire_task_access(
                mapping.user_id, mapping.connection_id
            )
            task = await self._provider.get_task(access, mapping.provider_list_ref, task_ref)
        except (TaskAccessError, TaskProviderError):
            return _decision(ReminderCompletionOutcome.SEND_UNAVAILABLE, "provider_unavailable")
        if task is None:
            await self._detach(mapping)
            return _decision(ReminderCompletionOutcome.SEND_UNAVAILABLE, "task_missing")
        observed = await self._observe(mapping, task.completed, task.revision)
        if observed is None:
            return _decision(ReminderCompletionOutcome.SEND_STALE, "mapping_changed")
        if not task.completed:
            return _decision(ReminderCompletionOutcome.SEND_NOT_COMPLETED, "task_not_completed")
        try:
            await self._actions.complete_agenda(
                observed.user_id,
                observed.agenda_entry_id,
                observed.agenda_entry_version,
                _completion_key(observed, task.revision),
            )
        except (LookupError, RuntimeError, ValueError):
            return _decision(ReminderCompletionOutcome.SEND_STALE, "action_not_completed")
        return _decision(ReminderCompletionOutcome.SUPPRESS_COMPLETED, "verified_completed")

    async def _validate_mapping(
        self, mapping: TaskProjectionMapping
    ) -> ReminderCompletionDecision | None:
        if mapping.status is not TaskProjectionStatus.ACTIVE:
            return _decision(ReminderCompletionOutcome.SEND_STALE, "mapping_not_active")
        target = await self._targets.get_for_connection(mapping.connection_id)
        if (
            target is None
            or target.user_id != mapping.user_id
            or target.status is not TaskProjectionTargetStatus.READY
            or target.provider_list_ref != mapping.provider_list_ref
        ):
            return _decision(ReminderCompletionOutcome.SEND_STALE, "target_mismatch")
        entry = await self._agenda.get_entry(mapping.agenda_entry_id)
        if (
            entry is None
            or entry.status != "ACTIVE"
            or entry.version != mapping.agenda_entry_version
        ):
            return _decision(ReminderCompletionOutcome.SEND_STALE, "agenda_mismatch")
        return None

    async def _observe(
        self, mapping: TaskProjectionMapping, completed: bool, revision: str | None
    ) -> TaskProjectionMapping | None:
        previous = mapping.version
        mapping.observe(completed, revision, self._clock.now())
        try:
            await self._mappings.save(mapping, previous)
        except RuntimeError:
            current = await self._mappings.get_for_agenda(
                mapping.connection_id, mapping.agenda_entry_id
            )
            if not _same_projection(mapping, current):
                return None
            return current
        return mapping

    async def _detach(self, mapping: TaskProjectionMapping) -> None:
        previous = mapping.version
        mapping.detach()
        try:
            await self._mappings.save(mapping, previous)
        except RuntimeError:
            return


class ReminderCompletionGate:
    def __init__(
        self,
        mappings: TaskProjectionMappingRepository,
        coordinator: TaskCompletionCoordinator,
        timeout_seconds: float = 3.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("completion gate timeout must be positive")
        self._mappings = mappings
        self._coordinator = coordinator
        self._timeout_seconds = timeout_seconds

    async def evaluate_before_delivery(
        self, user_id: str, agenda_entry_id: UUID, agenda_entry_version: int
    ) -> ReminderCompletionDecision:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._evaluate(user_id, agenda_entry_id, agenda_entry_version)
        except Exception:
            return _decision(ReminderCompletionOutcome.SEND_UNAVAILABLE, "gate_unavailable")

    async def _evaluate(
        self, user_id: str, agenda_entry_id: UUID, agenda_entry_version: int
    ) -> ReminderCompletionDecision:
        mappings = await self._mappings.list_for_agenda(agenda_entry_id)
        eligible = tuple(
            item
            for item in mappings
            if item.user_id == user_id
            and item.agenda_entry_version == agenda_entry_version
            and item.status is TaskProjectionStatus.ACTIVE
        )
        if not eligible:
            outcome = (
                ReminderCompletionOutcome.SEND_STALE
                if mappings
                else ReminderCompletionOutcome.SEND_UNMAPPED
            )
            return _decision(outcome, "no_current_mapping")
        fallback = _decision(ReminderCompletionOutcome.SEND_UNAVAILABLE, "provider_unavailable")
        for mapping in eligible:
            result = await self._coordinator.verify(mapping)
            if result.suppress:
                return result
            if result.outcome is ReminderCompletionOutcome.SEND_NOT_COMPLETED or (
                result.outcome is ReminderCompletionOutcome.SEND_STALE
                and fallback.outcome is not ReminderCompletionOutcome.SEND_NOT_COMPLETED
            ):
                fallback = result
        return fallback


def _completion_key(mapping: TaskProjectionMapping, revision: str | None) -> str:
    raw = f"{mapping.connection_id}:{mapping.mapping_id}:{revision or 'none'}"
    return f"todo-complete:{sha256(raw.encode()).hexdigest()}"


def _decision(outcome: ReminderCompletionOutcome, reason: str) -> ReminderCompletionDecision:
    return ReminderCompletionDecision(outcome, reason)


def _same_projection(
    expected: TaskProjectionMapping, current: TaskProjectionMapping | None
) -> bool:
    return (
        current is not None
        and current.status is TaskProjectionStatus.ACTIVE
        and current.user_id == expected.user_id
        and current.agenda_entry_id == expected.agenda_entry_id
        and current.agenda_entry_version == expected.agenda_entry_version
        and current.connection_id == expected.connection_id
        and current.provider_list_ref == expected.provider_list_ref
        and current.provider_task_ref == expected.provider_task_ref
    )
