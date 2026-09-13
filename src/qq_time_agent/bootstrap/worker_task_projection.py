"""Worker-only composition for Agenda-to-task projection."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.inbound.workers.task_projection import (
    CLOSE_JOB,
    DELTA_JOB,
    RECONCILE_JOB,
    UPSERT_JOB,
    AgendaProjectionOutboxRelay,
    AgendaProjectionReconciliationScheduler,
    TaskCompletionDeltaScheduler,
    TaskCompletionJobHandler,
    TaskProjectionJobHandler,
)
from qq_time_agent.adapters.outbound.microsoft_graph.todo import MicrosoftGraphTodoAdapter
from qq_time_agent.adapters.outbound.persistence.outbox import SqlOutbox
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease, JobQueue
from qq_time_agent.modules.actions.contracts import AgendaCompletionPort
from qq_time_agent.modules.agenda.contracts import AgendaProjectionQueryPort, AgendaQueryPort
from qq_time_agent.modules.connections.application.ports import MicrosoftConnectionProvider
from qq_time_agent.modules.connections.application.task_access import MicrosoftTaskAccessService
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher
from qq_time_agent.modules.credentials.infrastructure.repository import SqlCredentialRepository
from qq_time_agent.modules.task_projection.application import (
    TaskCompletionCoordinator,
    TaskCompletionSyncService,
    TaskProjectionService,
)
from qq_time_agent.modules.task_projection.infrastructure import (
    SqlTaskProjectionCursorRepository,
    SqlTaskProjectionMappingRepository,
    SqlTaskProjectionTargetRepository,
)


class WorkerAgenda(AgendaQueryPort, AgendaProjectionQueryPort, Protocol):
    pass


@dataclass(frozen=True, slots=True)
class WorkerTaskProjection:
    graph: MicrosoftGraphTodoAdapter
    relay: AgendaProjectionOutboxRelay
    reconciliation: AgendaProjectionReconciliationScheduler
    delta: TaskCompletionDeltaScheduler
    handler: TaskProjectionJobHandler
    completion_handler: TaskCompletionJobHandler

    def handlers(self) -> dict[str, Callable[[JobLease], Awaitable[None]]]:
        return {
            UPSERT_JOB: self.handler,
            CLOSE_JOB: self.handler,
            RECONCILE_JOB: self.handler,
            DELTA_JOB: self.completion_handler,
        }

    async def schedule_due(self) -> None:
        await self.relay.enqueue_due()
        await self.reconciliation.enqueue_due()
        await self.delta.enqueue_due()


def build_worker_task_projection(
    sessions: async_sessionmaker[AsyncSession],
    queue: JobQueue,
    agenda: WorkerAgenda,
    graph_connection: MicrosoftConnectionProvider,
    actions: AgendaCompletionPort,
    encryption_key: SecretStr,
    clock: Clock,
) -> WorkerTaskProjection:
    graph = MicrosoftGraphTodoAdapter(clock)
    targets = SqlTaskProjectionTargetRepository(sessions)
    mappings = SqlTaskProjectionMappingRepository(sessions)
    access = MicrosoftTaskAccessService(
        SqlConnectionRepository(sessions),
        VaultService(
            SqlCredentialRepository(sessions),
            AesGcmCredentialCipher(encryption_key),
            clock,
        ),
        graph_connection,
        clock,
    )
    service = TaskProjectionService(
        targets,
        mappings,
        agenda,
        access,
        graph,
        clock,
    )
    coordinator = TaskCompletionCoordinator(
        targets, mappings, agenda, access, graph, actions, clock
    )
    completion = TaskCompletionSyncService(
        targets,
        mappings,
        SqlTaskProjectionCursorRepository(sessions),
        access,
        graph,
        coordinator,
        clock,
    )
    return WorkerTaskProjection(
        graph,
        AgendaProjectionOutboxRelay(SqlOutbox(sessions), queue, clock),
        AgendaProjectionReconciliationScheduler(agenda, queue, clock),
        TaskCompletionDeltaScheduler(targets, queue, clock),
        TaskProjectionJobHandler(service),
        TaskCompletionJobHandler(completion),
    )
