"""Worker process entry and dependency composition."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.inbound.workers.agent_run import (
    AgentRunJobHandler,
    MailAgentRunScheduler,
)
from qq_time_agent.adapters.inbound.workers.data_lifecycle import DataLifecycleJobHandler
from qq_time_agent.adapters.inbound.workers.knowledge import (
    KnowledgeAssetIndexJobHandler,
    KnowledgeIndexJobHandler,
)
from qq_time_agent.adapters.inbound.workers.mail_sync import MailSyncJobHandler
from qq_time_agent.adapters.inbound.workers.runner import JobRunner
from qq_time_agent.adapters.inbound.workers.source_asset import (
    SourceAssetFetchJobHandler,
    SourceAssetParseJobHandler,
)
from qq_time_agent.adapters.outbound.ai.deepseek import DeepSeekStructuredAdapter
from qq_time_agent.adapters.outbound.ollama.embedding import OllamaEmbeddingAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.jobs import SqlJobQueue
from qq_time_agent.adapters.outbound.persistence.retention import OperationalExpiryAdapter
from qq_time_agent.bootstrap.logging import configure_logging
from qq_time_agent.bootstrap.runtime import configure_event_loop_policy
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.bootstrap.worker_assets import build_worker_asset_services
from qq_time_agent.bootstrap.worker_calendar import build_calendar_change_handler
from qq_time_agent.bootstrap.worker_connections import build_worker_mail_connections
from qq_time_agent.bootstrap.worker_notifications import build_notification_planner
from qq_time_agent.bootstrap.worker_runtime import build_scheduled_runner
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.contracts.jobs import JobLease
from qq_time_agent.contracts.source import SourceType
from qq_time_agent.contracts.tools import ToolDispatcher
from qq_time_agent.modules.actions.application.service import ActionService
from qq_time_agent.modules.actions.infrastructure.repository import SqlActionRepository
from qq_time_agent.modules.agenda.application.notification_query import (
    AgendaNotificationQueryService,
)
from qq_time_agent.modules.agenda.application.service import AgendaService
from qq_time_agent.modules.agenda.application.source_lookup import AgendaSourceLookupService
from qq_time_agent.modules.agenda.infrastructure.repository import SqlAgendaRepository
from qq_time_agent.modules.agent.application.budget import ContextBudgetPolicy
from qq_time_agent.modules.agent.application.context import AgentContextAssembler
from qq_time_agent.modules.agent.application.json_model import JsonAgentModel
from qq_time_agent.modules.agent.application.loop import AgentLoop, AgentLoopConfig
from qq_time_agent.modules.agent.application.run_service import AgentRunService
from qq_time_agent.modules.agent.infrastructure.events import SqlAgentRunEventRepository
from qq_time_agent.modules.agent.infrastructure.repository import SqlAgentRunRepository
from qq_time_agent.modules.ai_gateway.application.service import AIGatewayService
from qq_time_agent.modules.ai_gateway.infrastructure.repository import SqlInvocationRepository
from qq_time_agent.modules.ai_gateway.infrastructure.retention import AIGatewayExpiryAdapter
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.audit.infrastructure.retention import AuditExpiryAdapter
from qq_time_agent.modules.calendar_system.application.authorization import (
    OwnerCalendarAuthorization,
)
from qq_time_agent.modules.calendar_system.application.tools import CalendarToolRegistry
from qq_time_agent.modules.connections.application.status import ConnectionStatusQueryService
from qq_time_agent.modules.connections.application.tools import ConnectionStatusToolRegistry
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.data_lifecycle.application.coordinator import (
    DeletionCoordinator,
    ExpiryTarget,
    RetentionCoordinator,
)
from qq_time_agent.modules.data_lifecycle.infrastructure.repository import SqlTombstoneRepository
from qq_time_agent.modules.identity.application.aliases import OwnerGroupAliasService
from qq_time_agent.modules.identity.application.service import UserPreferencesService
from qq_time_agent.modules.identity.application.tools import OwnerGroupAliasToolRegistry
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.identity.infrastructure.repository import (
    SqlOwnerGroupAliasRepository,
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
from qq_time_agent.modules.notifications.application.agent_results import (
    AgentMailResultNotificationService,
)
from qq_time_agent.modules.notifications.infrastructure.repository import (
    SqlNotificationIntentRepository,
)
from qq_time_agent.modules.reminders.application.service import ReminderService
from qq_time_agent.modules.reminders.infrastructure.repository import SqlReminderRepository
from qq_time_agent.modules.retrieval.application.service import HybridRetrievalService
from qq_time_agent.modules.scheduling.application.pending_query import PendingProposalQueryService
from qq_time_agent.modules.scheduling.infrastructure.purge import SchedulingPurgeAdapter
from qq_time_agent.modules.scheduling.infrastructure.repository import SqlProposalRepository
from qq_time_agent.modules.understanding.infrastructure.purge import UnderstandingPurgeAdapter
from qq_time_agent.modules.workflow.infrastructure.purge import WorkflowPurgeAdapter


class AsyncClosable(Protocol):
    async def close(self) -> None: ...


def build_worker() -> tuple[JobRunner, AsyncEngine, tuple[AsyncClosable, ...]]:
    config = load_runtime_config()
    clock = SystemClock()
    engine = create_database_engine(config.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    queue = SqlJobQueue(sessions)
    context_policy = ContextBudgetPolicy(
        config.agent_context.max_context_tokens,
        safety_margin_tokens=config.agent_context.safety_margin_tokens,
    )
    deepseek = DeepSeekStructuredAdapter(config.deepseek)
    ollama = OllamaEmbeddingAdapter(config.ollama)
    audit = AuditService(SqlAuditRepository(sessions))
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
    source_deletion = ConnectionSourceDeletionService(
        SqlConnectionInboxDeletionRepository(sessions), deletion, clock
    )
    mail = build_worker_mail_connections(config, sessions, queue, source_deletion, audit, clock)
    connections = mail.microsoft
    qq_connections = mail.qq
    graph_connection = mail.graph_connection
    graph_mail = mail.graph_mail
    qq_mail = mail.qq_mail

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
    assets = build_worker_asset_services(
        config.assets,
        str(config.schedule.timezone),
        sessions,
        queue,
        connections,
        qq_connections,
        graph_mail,
        qq_mail,
        clock,
    )
    knowledge = KnowledgeIndexService(
        knowledge_repository,
        ollama,
        config.ollama.model,
        config.ollama.dimensions,
        config.ollama.index_version,
    )
    retrieval = HybridRetrievalService(
        knowledge_repository,
        ollama,
        config.ollama.model,
        config.ollama.dimensions,
        config.ollama.index_version,
        config.rag_vector_weight,
        config.rag_lexical_weight,
        config.rag_retrieval_limit,
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
        asset_discovery=assets.discovery,
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
        assets.discovery,
    )
    model = AIGatewayService(
        deepseek, SqlInvocationRepository(sessions), clock, config.deepseek.max_concurrency
    )
    retrieval.configure_query_model(model)
    agent_model = JsonAgentModel(
        model,
        max_context_tokens=config.agent_context.max_context_tokens,
        safety_margin_tokens=config.agent_context.safety_margin_tokens,
    )
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
    owner_aliases = OwnerGroupAliasService(SqlOwnerGroupAliasRepository(sessions), clock)
    agenda_repository = SqlAgendaRepository(sessions)
    agenda = AgendaService(agenda_repository)
    reminders = ReminderService(SqlReminderRepository(sessions))
    actions = ActionService(
        SqlActionRepository(sessions),
        agenda,
        reminders,
        clock,
        audit,
        agenda,
    )
    agent = AgentLoop(
        agent_model,
        ToolDispatcher(
            CalendarToolRegistry(
                agenda, actions, OwnerCalendarAuthorization("owner"), str(config.schedule.timezone)
            ),
            OwnerGroupAliasToolRegistry(owner_aliases),
            ConnectionStatusToolRegistry(
                ConnectionStatusQueryService(SqlConnectionRepository(sessions))
            ),
        ),
        config=AgentLoopConfig(
            model_output_token_budget=config.agent_context.model_output_token_budget,
            max_output_tokens_per_request=config.agent_context.max_output_tokens_per_request,
            observation_token_budget=config.agent_context.observation_tokens,
        ),
        owner_timezone=str(config.schedule.timezone),
        clock=clock,
    )
    run_repository = SqlAgentRunRepository(sessions)
    run_event_repository = SqlAgentRunEventRepository(sessions)
    agent_context = AgentContextAssembler(
        retrieval,
        inbox,
        run_repository,
        inbox_repository,
        AgendaNotificationQueryService(agenda_repository),
        PendingProposalQueryService(SqlProposalRepository(sessions), clock),
        str(config.schedule.timezone),
        owner_aliases,
        budget=context_policy,
        retrieval_limit=config.agent_context.retrieval_limit,
        history_limit=config.agent_context.history_limit,
    )
    agent_runs = AgentRunService(run_repository, agent, clock, events=run_event_repository)
    agent_scheduler = MailAgentRunScheduler(
        agent_runs, inbox_repository, inbox_repository, queue, clock
    )
    microsoft_sync.set_agent_scheduler(agent_scheduler)
    qq_sync.set_agent_scheduler(agent_scheduler)
    agenda_lookup = AgendaSourceLookupService(agenda_repository)
    handlers: dict[str, Callable[[JobLease], Awaitable[None]]] = {
        "microsoft-mail-sync": MailSyncJobHandler(microsoft_sync),
        "qq-mail-sync": MailSyncJobHandler(qq_sync),
        "source-asset-fetch": SourceAssetFetchJobHandler(assets.fetch, clock),
        "source-asset-parse": SourceAssetParseJobHandler(assets.parse, clock),
        "calendar-change-ingest": build_calendar_change_handler(
            sessions,
            assets.normalized,
            agenda_lookup,
            config.credential_encryption_key,
            clock,
        ),
        "agent-run": AgentRunJobHandler(
            agent_runs,
            inbox_repository,
            agent_context,
            inbox_repository,
            AgentMailResultNotificationService(SqlNotificationIntentRepository(sessions)),
            clock,
        ),
        "knowledge-index": KnowledgeIndexJobHandler(
            inbox_repository, inbox_repository, normalization_repository, knowledge
        ),
        "knowledge-asset-index": KnowledgeAssetIndexJobHandler(
            inbox_repository, normalization_repository, assets.normalized, knowledge
        ),
        "data-lifecycle-sweep": DataLifecycleJobHandler(
            deletion,
            retention,
            assets.cleanup,
            assets.discovery,
            clock,
        ),
    }
    runner = build_scheduled_runner(
        queue,
        handlers,
        clock,
        config.mail_sync_interval_seconds,
        connections,
        qq_connections,
        inbox,
        inbox_repository,
        inbox_repository,
        inbox_repository,
        ollama,
        build_notification_planner(sessions, preferences, agenda_repository),
    )

    return (
        runner,
        engine,
        (
            graph_connection,
            graph_mail,
            qq_mail,
            deepseek,
            ollama,
            assets.qq_media,
        ),
    )


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
    configure_logging(role="worker")
    asyncio.run(run_worker())
