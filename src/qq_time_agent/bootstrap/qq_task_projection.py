"""QQ-process composition for the reminder completion gate."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.outbound.microsoft_graph.connection import (
    MicrosoftGraphConnectionAdapter,
)
from qq_time_agent.adapters.outbound.microsoft_graph.todo import MicrosoftGraphTodoAdapter
from qq_time_agent.bootstrap.config_models import RuntimeConfig
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.actions.contracts import AgendaCompletionPort
from qq_time_agent.modules.agenda.contracts import AgendaQueryPort
from qq_time_agent.modules.connections.application.task_access import MicrosoftTaskAccessService
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher
from qq_time_agent.modules.credentials.infrastructure.repository import SqlCredentialRepository
from qq_time_agent.modules.task_projection.application import (
    ReminderCompletionGate,
    TaskCompletionCoordinator,
)
from qq_time_agent.modules.task_projection.infrastructure import (
    SqlTaskProjectionMappingRepository,
    SqlTaskProjectionTargetRepository,
)


@dataclass(frozen=True, slots=True)
class QqTaskCompletion:
    gate: ReminderCompletionGate
    graph_connection: MicrosoftGraphConnectionAdapter
    graph_todo: MicrosoftGraphTodoAdapter

    async def close(self) -> None:
        await self.graph_todo.close()
        await self.graph_connection.close()


def build_qq_task_completion(
    config: RuntimeConfig,
    sessions: async_sessionmaker[AsyncSession],
    agenda: AgendaQueryPort,
    actions: AgendaCompletionPort,
    clock: Clock,
) -> QqTaskCompletion:
    graph_connection = MicrosoftGraphConnectionAdapter(config.microsoft, clock, max_attempts=1)
    graph_todo = MicrosoftGraphTodoAdapter(clock, timeout_seconds=2.5, max_attempts=1)
    access = MicrosoftTaskAccessService(
        SqlConnectionRepository(sessions),
        VaultService(
            SqlCredentialRepository(sessions),
            AesGcmCredentialCipher(config.credential_encryption_key),
            clock,
        ),
        graph_connection,
        clock,
    )
    mappings = SqlTaskProjectionMappingRepository(sessions)
    coordinator = TaskCompletionCoordinator(
        SqlTaskProjectionTargetRepository(sessions),
        mappings,
        agenda,
        access,
        graph_todo,
        actions,
        clock,
    )
    return QqTaskCompletion(
        ReminderCompletionGate(mappings, coordinator), graph_connection, graph_todo
    )
