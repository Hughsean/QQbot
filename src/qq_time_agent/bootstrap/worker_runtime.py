"""Worker scheduler assembly and durable runner creation."""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from qq_time_agent.adapters.inbound.workers.data_lifecycle_schedule import DataLifecycleScheduler
from qq_time_agent.adapters.inbound.workers.knowledge_schedule import KnowledgeIndexScheduler
from qq_time_agent.adapters.inbound.workers.mail_schedule import (
    ConnectionStatusLookup,
    PeriodicMailSyncScheduler,
)
from qq_time_agent.adapters.inbound.workers.notification_schedule import (
    NotificationPlanner,
    NotificationPlanningScheduler,
)
from qq_time_agent.adapters.inbound.workers.provider_readiness import EmbeddingStartupGate
from qq_time_agent.adapters.inbound.workers.runner import JobRunner
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobLease, JobQueue
from qq_time_agent.modules.embeddings.contracts import EmbeddingPort
from qq_time_agent.modules.inbox.contracts import (
    InboxContentPort,
    InboxKnowledgeQueryPort,
    InboxProcessingQueryPort,
    InboxSourcePort,
)


def build_scheduled_runner(
    queue: JobQueue,
    handlers: dict[str, Callable[[JobLease], Awaitable[None]]],
    clock: Clock,
    mail_interval_seconds: int,
    microsoft_connections: ConnectionStatusLookup,
    qq_connections: ConnectionStatusLookup,
    inbox: InboxProcessingQueryPort,
    knowledge_query: InboxKnowledgeQueryPort,
    content: InboxContentPort,
    sources: InboxSourcePort,
    embeddings: EmbeddingPort,
    notification_planner: NotificationPlanner,
    before_start: Callable[[], Awaitable[None]] | None = None,
) -> JobRunner:
    schedulers = (
        PeriodicMailSyncScheduler(microsoft_connections, queue, clock, mail_interval_seconds),
        PeriodicMailSyncScheduler(
            qq_connections, queue, clock, mail_interval_seconds, "qq-mail-sync"
        ),
        KnowledgeIndexScheduler(knowledge_query, content, sources, queue, clock),
        DataLifecycleScheduler(queue, clock),
        NotificationPlanningScheduler(notification_planner, clock),
    )

    async def schedule_due() -> None:
        for scheduler in schedulers:
            await scheduler.enqueue_due()

    async def run_before_start() -> None:
        if before_start is not None:
            await before_start()
        await EmbeddingStartupGate(embeddings).wait()

    return JobRunner(
        queue,
        handlers,
        clock,
        f"worker-{uuid4()}",
        before_poll=schedule_due,
        before_start=run_before_start,
    )
