"""Cursor-based completion synchronization for managed task lists."""

from uuid import UUID

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.connections.contracts import TaskAccessError, TaskConnectionAccessPort
from qq_time_agent.modules.task_projection.application.completion import (
    TaskCompletionCoordinator,
)
from qq_time_agent.modules.task_projection.application.ports import (
    TaskProjectionCursorRepository,
    TaskProjectionMappingRepository,
    TaskProjectionTargetRepository,
)
from qq_time_agent.modules.task_projection.contracts import (
    ReminderCompletionOutcome,
    TaskProviderError,
    TaskProviderPort,
)
from qq_time_agent.modules.task_projection.domain import TaskProjectionCursor


class TaskCompletionSyncError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


class TaskCompletionSyncService:
    def __init__(
        self,
        targets: TaskProjectionTargetRepository,
        mappings: TaskProjectionMappingRepository,
        cursors: TaskProjectionCursorRepository,
        connections: TaskConnectionAccessPort,
        provider: TaskProviderPort,
        coordinator: TaskCompletionCoordinator,
        clock: Clock,
        owner_id: str = "owner",
    ) -> None:
        self._targets = targets
        self._mappings = mappings
        self._cursors = cursors
        self._connections = connections
        self._provider = provider
        self._coordinator = coordinator
        self._clock = clock
        self._owner_id = owner_id

    async def sync_target(self, connection_id: UUID) -> int:
        target = await self._targets.get_for_connection(connection_id)
        if target is None or target.user_id != self._owner_id or not target.is_ready:
            return 0
        cursor = await self._cursors.get(connection_id, target.provider_list_ref)
        try:
            access = await self._connections.acquire_task_access(self._owner_id, connection_id)
            page = await self._provider.fetch_delta(
                access,
                target.provider_list_ref,
                None if cursor is None else cursor.opaque_cursor,
            )
        except TaskProviderError as exc:
            if exc.failure_class == "CursorInvalid":
                await self._cursors.delete(connection_id, target.provider_list_ref)
                return 0
            raise TaskCompletionSyncError(exc.failure_class) from exc
        except TaskAccessError as exc:
            raise TaskCompletionSyncError(exc.failure_class) from exc
        completed = 0
        for change in page.changes:
            if change.removed or not change.completed:
                continue
            mapping = await self._mappings.get_for_external_task(
                connection_id, target.provider_list_ref, change.task_ref
            )
            if mapping is None:
                continue
            decision = await self._coordinator.verify(mapping)
            if decision.outcome is ReminderCompletionOutcome.SUPPRESS_COMPLETED:
                completed += 1
            elif decision.reason in {
                "action_not_completed",
                "gate_unavailable",
                "mapping_changed",
                "provider_unavailable",
            }:
                raise TaskCompletionSyncError("TransientProvider")
        await self._advance_cursor(
            connection_id, target.provider_list_ref, page.continuation, cursor
        )
        return completed

    async def _advance_cursor(
        self,
        connection_id: UUID,
        list_ref: str,
        continuation: str,
        cursor: TaskProjectionCursor | None,
    ) -> None:
        if cursor is None:
            await self._cursors.save(
                TaskProjectionCursor.create(
                    connection_id, list_ref, continuation, self._clock.now()
                ),
                None,
            )
            return
        previous = cursor.version
        cursor.advance(continuation, self._clock.now())
        await self._cursors.save(cursor, previous)
