"""Worker process entry and dependency composition."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.inbound.workers.data_lifecycle import DataLifecycleJobHandler
from qq_time_agent.adapters.inbound.workers.data_lifecycle_schedule import DataLifecycleScheduler
from qq_time_agent.adapters.inbound.workers.knowledge import KnowledgeIndexJobHandler
from qq_time_agent.adapters.inbound.workers.knowledge_schedule import KnowledgeIndexScheduler
from qq_time_agent.adapters.inbound.workers.mail_schedule import PeriodicMailSyncScheduler
from qq_time_agent.adapters.inbound.workers.mail_sync import MailSyncJobHandler
from qq_time_agent.adapters.inbound.workers.runner import JobRunner
from qq_time_agent.adapters.inbound.workers.scheduling import SchedulingJobHandler
from qq_time_agent.adapters.inbound.workers.scheduling_schedule import SchedulingScheduler
from qq_time_agent.adapters.inbound.workers.understanding import UnderstandingJobHandler
from qq_time_agent.adapters.inbound.workers.understanding_schedule import UnderstandingScheduler
from qq_time_agent.adapters.outbound.ai.deepseek import DeepSeekStructuredAdapter
from qq_time_agent.adapters.outbound.microsoft_graph.connection import (
    MicrosoftGraphConnectionAdapter,
)
from qq_time_agent.adapters.outbound.microsoft_graph.mail import MicrosoftGraphMailAdapter
from qq_time_agent.adapters.outbound.ollama.embedding import OllamaEmbeddingAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.jobs import SqlJobQueue
from qq_time_agent.adapters.outbound.persistence.retention import OperationalExpiryAdapter
from qq_time_agent.adapters.outbound.qq_mail.imap import QqMailImapAdapter
from qq_time_agent.bootstrap.logging import configure_logging
from qq_time_agent.bootstrap.runtime import configure_event_loop_policy
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.agenda.application.service import AgendaService
from qq_time_agent.modules.agenda.infrastructure.repository import SqlAgendaRepository
from qq_time_agent.modules.ai_gateway.application.service import AIGatewayService
from qq_time_agent.modules.ai_gateway.infrastructure.repository import SqlInvocationRepository
from qq_time_agent.modules.ai_gateway.infrastructure.retention import AIGatewayExpiryAdapter
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.audit.infrastructure.retention import AuditExpiryAdapter
from qq_time_agent.modules.connections.application.oauth import MicrosoftConnectionService
from qq_time_agent.modules.connections.application.qq_mail import QqMailConnectionService
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher
from qq_time_agent.modules.credentials.infrastructure.repository import SqlCredentialRepository
from qq_time_agent.modules.data_lifecycle.application.coordinator import (
    DeletionCoordinator,
    ExpiryTarget,
    RetentionCoordinator,
)
from qq_time_agent.modules.data_lifecycle.infrastructure.repository import SqlTombstoneRepository
from qq_time_agent.modules.identity.application.service import UserPreferencesService
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.identity.infrastructure.repository import (
    SqlUserPreferencesRepository,
)
from qq_time_agent.modules.inbox.application.connection_deletion import (
    ConnectionSourceDeletionService,
)
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.application.sync import MailSyncService
from qq_time_agent.modules.inbox.infrastructure.connection_deletion import (
    SqlConnectionInboxDeletionRepository,
)
from qq_time_agent.modules.inbox.infrastructure.purge import InboxPurgeAdapter
from qq_time_agent.modules.inbox.infrastructure.repository import SqlInboxRepository
from qq_time_agent.modules.inbox.infrastructure.retention import InboxExpiredSourceAdapter
from qq_time_agent.modules.knowledge.application.service import KnowledgeIndexService
from qq_time_agent.modules.knowledge.infrastructure.purge import KnowledgePurgeAdapter
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository
from qq_time_agent.modules.normalization.application.service import NormalizationService
from qq_time_agent.modules.normalization.infrastructure.purge import NormalizationPurgeAdapter
from qq_time_agent.modules.normalization.infrastructure.repository import (
    SqlNormalizedContentRepository,
)
from qq_time_agent.modules.scheduling.application.service import SchedulingService
from qq_time_agent.modules.scheduling.infrastructure.purge import SchedulingPurgeAdapter
from qq_time_agent.modules.scheduling.infrastructure.repository import SqlProposalRepository
from qq_time_agent.modules.understanding.application.query import CandidateQueryService
from qq_time_agent.modules.understanding.application.service import (
    TemporalContext,
    UnderstandingService,
)
from qq_time_agent.modules.understanding.infrastructure.purge import UnderstandingPurgeAdapter
from qq_time_agent.modules.understanding.infrastructure.repository import (
    SqlCandidateRepository,
)
from qq_time_agent.modules.workflow.application.understanding_graph import (
    UnderstandingWorkflow,
)
from qq_time_agent.modules.workflow.infrastructure.purge import WorkflowPurgeAdapter
from qq_time_agent.modules.workflow.infrastructure.repository import (
    SqlWorkflowCheckpointRepository,
)


class AsyncClosable(Protocol):
    async def close(self) -> None: ...


def build_worker() -> tuple[JobRunner, AsyncEngine, tuple[AsyncClosable, ...]]:
    config = load_runtime_config()
    clock = SystemClock()
    engine = create_database_engine(config.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    queue = SqlJobQueue(sessions)
    graph_connection = MicrosoftGraphConnectionAdapter(config.microsoft, clock)
    graph_mail = MicrosoftGraphMailAdapter(clock)
    deepseek = DeepSeekStructuredAdapter(config.deepseek)
    ollama = OllamaEmbeddingAdapter(config.ollama)
    audit = AuditService(SqlAuditRepository(sessions))
    connection_repository = SqlConnectionRepository(sessions)
    vault = VaultService(
        SqlCredentialRepository(sessions),
        AesGcmCredentialCipher(config.credential_encryption_key),
        clock,
    )
    connections = MicrosoftConnectionService(
        connection_repository,
        vault,
        graph_connection,
        clock,
        audit=audit,
    )
    inbox_repository = SqlInboxRepository(sessions)
    inbox = InboxService(inbox_repository)
    normalization_repository = SqlNormalizedContentRepository(sessions)
    knowledge_repository = SqlKnowledgeRepository(sessions)
    deletion = DeletionCoordinator(
        SqlTombstoneRepository(sessions, clock),
        (
            SchedulingPurgeAdapter(sessions),
            UnderstandingPurgeAdapter(sessions),
            WorkflowPurgeAdapter(sessions),
            KnowledgePurgeAdapter(knowledge_repository),
            NormalizationPurgeAdapter(sessions),
            InboxPurgeAdapter(sessions),
        ),
        clock,
        timedelta(hours=config.retention.source_deletion_hours),
        audit,
    )
    qq_mail = QqMailImapAdapter(config.qq_mail, clock)
    qq_connections = QqMailConnectionService(
        connection_repository,
        vault,
        qq_mail,
        queue,
        ConnectionSourceDeletionService(
            SqlConnectionInboxDeletionRepository(sessions), deletion, clock
        ),
        clock,
        audit,
    )
    retention = RetentionCoordinator(
        deletion,
        InboxExpiredSourceAdapter(sessions),
        timedelta(days=config.retention.source_content_days),
        (
            ExpiryTarget(
                AIGatewayExpiryAdapter(sessions),
                timedelta(days=config.retention.ai_metadata_days),
            ),
            ExpiryTarget(AuditExpiryAdapter(sessions), timedelta(days=config.retention.audit_days)),
            ExpiryTarget(
                OperationalExpiryAdapter(sessions),
                timedelta(days=config.retention.operational_days),
            ),
        ),
        clock,
    )
    knowledge = KnowledgeIndexService(
        knowledge_repository,
        ollama,
        config.ollama.model,
        config.ollama.dimensions,
        config.ollama.index_version,
    )
    microsoft_sync = MailSyncService(
        connections,
        inbox,
        inbox_repository,
        NormalizationService(normalization_repository),
        graph_mail,
        clock,
        config.mail_initial_lookback_days,
        deletion,
    )
    qq_sync = MailSyncService(
        qq_connections,
        inbox,
        inbox_repository,
        NormalizationService(normalization_repository),
        qq_mail,
        clock,
        config.mail_initial_lookback_days,
        deletion,
        SourceType.QQ_MAIL,
    )
    model = AIGatewayService(
        deepseek, SqlInvocationRepository(sessions), clock, config.deepseek.max_concurrency
    )
    understanding = UnderstandingService(
        normalization_repository,
        inbox_repository,
        model,
        SqlCandidateRepository(sessions),
        TemporalContext(
            str(config.schedule.timezone),
            "owner",
            config.schedule.default_item_minutes,
        ),
    )
    workflow = UnderstandingWorkflow(
        understanding, inbox, SqlWorkflowCheckpointRepository(sessions), inbox_repository
    )
    candidate_queries = CandidateQueryService(SqlCandidateRepository(sessions))
    preferences = UserPreferencesService(
        SqlUserPreferencesRepository(sessions),
        UserPreferencesView(
            "owner",
            str(config.schedule.timezone),
            config.schedule.work_start,
            config.schedule.work_end,
            config.schedule.lunch_start,
            config.schedule.lunch_end,
            (0, 1, 2, 3, 4),
            config.schedule.default_item_minutes,
            config.schedule.default_item_minutes,
        ),
    )
    scheduling = SchedulingService(
        candidate_queries,
        preferences,
        AgendaService(SqlAgendaRepository(sessions)),
        SqlProposalRepository(sessions),
        clock,
    )
    handlers: dict[str, Callable[[JobLease], Awaitable[None]]] = {
        "microsoft-mail-sync": MailSyncJobHandler(microsoft_sync),
        "qq-mail-sync": MailSyncJobHandler(qq_sync),
        "understanding-run": UnderstandingJobHandler(workflow),
        "scheduling-propose": SchedulingJobHandler(
            scheduling, candidate_queries, inbox, inbox_repository
        ),
        "knowledge-index": KnowledgeIndexJobHandler(
            inbox_repository, inbox_repository, normalization_repository, knowledge
        ),
        "data-lifecycle-sweep": DataLifecycleJobHandler(deletion, retention),
    }
    microsoft_mail_scheduler = PeriodicMailSyncScheduler(
        connections, queue, clock, config.mail_sync_interval_seconds
    )
    qq_mail_scheduler = PeriodicMailSyncScheduler(
        qq_connections, queue, clock, config.mail_sync_interval_seconds, "qq-mail-sync"
    )
    understanding_scheduler = UnderstandingScheduler(inbox, queue, clock)
    scheduling_scheduler = SchedulingScheduler(candidate_queries, queue, clock)
    knowledge_scheduler = KnowledgeIndexScheduler(
        inbox, inbox_repository, inbox_repository, queue, clock
    )
    lifecycle_scheduler = DataLifecycleScheduler(queue, clock)

    async def schedule_due() -> None:
        await microsoft_mail_scheduler.enqueue_due()
        await qq_mail_scheduler.enqueue_due()
        await understanding_scheduler.enqueue_due()
        await scheduling_scheduler.enqueue_due()
        await knowledge_scheduler.enqueue_due()
        await lifecycle_scheduler.enqueue_due()

    runner = JobRunner(queue, handlers, clock, f"worker-{uuid4()}", before_poll=schedule_due)
    return runner, engine, (graph_connection, graph_mail, qq_mail, deepseek, ollama)


async def run_worker() -> None:
    runner, engine, resources = build_worker()
    try:
        await runner.run_forever()
    finally:
        for resource in resources:
            await resource.close()
        await engine.dispose()


def main() -> None:
    configure_event_loop_policy()
    configure_logging()
    asyncio.run(run_worker())
