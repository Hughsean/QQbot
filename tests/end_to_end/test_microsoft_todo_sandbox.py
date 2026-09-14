"""Explicit live Microsoft To Do lifecycle check with guaranteed cleanup."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from qq_time_agent.adapters.outbound.microsoft_graph.connection import (
    MicrosoftGraphConnectionAdapter,
)
from qq_time_agent.adapters.outbound.microsoft_graph.todo import MicrosoftGraphTodoAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.modules.connections.application.task_access import MicrosoftTaskAccessService
from qq_time_agent.modules.connections.domain.models import ConnectionProvider, ConnectionStatus
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher
from qq_time_agent.modules.credentials.infrastructure.repository import SqlCredentialRepository
from qq_time_agent.modules.task_projection.application.managed_list import ManagedTaskListService
from qq_time_agent.modules.task_projection.contracts import ExternalTaskDraft
from qq_time_agent.modules.task_projection.infrastructure.repository import (
    SqlTaskProjectionTargetRepository,
)

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]


async def test_live_todo_create_read_complete_and_delete() -> None:
    try:
        await _live_todo_create_read_complete_and_delete()
    except Exception as exc:
        failure = getattr(exc, "failure_class", type(exc).__name__)
        if not isinstance(failure, str):
            failure = type(exc).__name__
        pytest.fail(f"live Microsoft To Do lifecycle failed: {failure}", pytrace=False)


async def _live_todo_create_read_complete_and_delete() -> None:
    config = load_runtime_config()
    clock = SystemClock()
    engine = create_database_engine(config.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    connections = SqlConnectionRepository(sessions)
    graph_connection = MicrosoftGraphConnectionAdapter(config.microsoft, clock, max_attempts=1)
    graph_todo = MicrosoftGraphTodoAdapter(clock, max_attempts=1)
    access = MicrosoftTaskAccessService(
        connections,
        VaultService(
            SqlCredentialRepository(sessions),
            AesGcmCredentialCipher(config.credential_encryption_key),
            clock,
        ),
        graph_connection,
        clock,
    )
    task_ref: str | None = None
    list_ref: str | None = None
    grant = None
    try:
        candidates = await connections.list_for_provider(
            "owner", ConnectionProvider.MICROSOFT.value
        )
        connection = next(
            (
                item
                for item in candidates
                if item.status in {ConnectionStatus.ACTIVE, ConnectionStatus.DEGRADED}
                and item.sync_enabled
                and "Tasks.ReadWrite" in item.capabilities
            ),
            None,
        )
        assert connection is not None, "active Microsoft Tasks.ReadWrite connection is required"
        target = await ManagedTaskListService(
            SqlTaskProjectionTargetRepository(sessions), access, graph_todo, clock
        ).resolve("owner", connection.connection_id)
        stored_target = await SqlTaskProjectionTargetRepository(sessions).get_for_connection(
            connection.connection_id
        )
        assert stored_target is not None
        list_ref = stored_target.provider_list_ref
        grant = await access.acquire_task_access("owner", connection.connection_id)
        start = clock.now() + timedelta(days=7)
        marker = f"qq-time-agent:sandbox:{uuid4().hex}"
        created = await graph_todo.upsert_task(
            grant,
            list_ref,
            ExternalTaskDraft(
                marker,
                "[沙箱] 小智 Microsoft To Do 联动验证",
                start,
                start + timedelta(minutes=15),
                "Asia/Shanghai",
            ),
            None,
        )
        task_ref = created.task_ref
        loaded = await graph_todo.get_task(grant, list_ref, task_ref)
        assert loaded is not None and not loaded.completed
        await graph_todo.close_task(grant, list_ref, task_ref, completed=True)
        completed = await graph_todo.get_task(grant, list_ref, task_ref)
        assert completed is not None and completed.completed
        assert target.status == "READY"
    finally:
        if task_ref is not None and list_ref is not None and grant is not None:
            await graph_todo.close_task(grant, list_ref, task_ref, completed=False)
        await graph_todo.close()
        await graph_connection.close()
        await engine.dispose()
