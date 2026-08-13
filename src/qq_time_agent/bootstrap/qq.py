"""QQ long-connection process composition root."""

import asyncio
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from qq_time_agent.adapters.inbound.qq.commands import QqCommandRouter
from qq_time_agent.adapters.inbound.qq.gateway import OfficialQqGateway
from qq_time_agent.adapters.inbound.workers.proposal_notifications import (
    ProposalNotificationWorker,
)
from qq_time_agent.adapters.inbound.workers.reminders import ReminderWorker
from qq_time_agent.adapters.outbound.ai.deepseek import DeepSeekStructuredAdapter
from qq_time_agent.adapters.outbound.ollama.embedding import OllamaEmbeddingAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.jobs import SqlJobQueue
from qq_time_agent.bootstrap.logging import configure_logging
from qq_time_agent.bootstrap.runtime import configure_event_loop_policy
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.modules.actions.application.service import ActionService
from qq_time_agent.modules.actions.infrastructure.repository import SqlActionRepository
from qq_time_agent.modules.agenda.application.service import AgendaService
from qq_time_agent.modules.agenda.infrastructure.repository import SqlAgendaRepository
from qq_time_agent.modules.ai_gateway.application.rag_answer import RetrievalAnswerService
from qq_time_agent.modules.ai_gateway.application.service import AIGatewayService
from qq_time_agent.modules.ai_gateway.infrastructure.repository import SqlInvocationRepository
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.data_lifecycle.application.coordinator import DeletionCoordinator
from qq_time_agent.modules.data_lifecycle.infrastructure.repository import SqlTombstoneRepository
from qq_time_agent.modules.identity.application.service import UserPreferencesService
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.identity.infrastructure.repository import (
    SqlUserPreferencesRepository,
)
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.infrastructure.purge import InboxPurgeAdapter
from qq_time_agent.modules.inbox.infrastructure.repository import SqlInboxRepository
from qq_time_agent.modules.knowledge.infrastructure.purge import KnowledgePurgeAdapter
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository
from qq_time_agent.modules.normalization.application.service import NormalizationService
from qq_time_agent.modules.normalization.infrastructure.purge import NormalizationPurgeAdapter
from qq_time_agent.modules.normalization.infrastructure.repository import (
    SqlNormalizedContentRepository,
)
from qq_time_agent.modules.notifications.application.service import NotificationService
from qq_time_agent.modules.notifications.infrastructure.repository import SqlDeliveryRepository
from qq_time_agent.modules.reminders.application.service import ReminderService
from qq_time_agent.modules.reminders.infrastructure.repository import SqlReminderRepository
from qq_time_agent.modules.retrieval.application.service import HybridRetrievalService
from qq_time_agent.modules.scheduling.application.service import SchedulingService
from qq_time_agent.modules.scheduling.infrastructure.purge import SchedulingPurgeAdapter
from qq_time_agent.modules.scheduling.infrastructure.repository import SqlProposalRepository
from qq_time_agent.modules.understanding.application.query import CandidateQueryService
from qq_time_agent.modules.understanding.infrastructure.purge import UnderstandingPurgeAdapter
from qq_time_agent.modules.understanding.infrastructure.repository import (
    SqlCandidateRepository,
)
from qq_time_agent.modules.workflow.infrastructure.purge import WorkflowPurgeAdapter


async def run_qq() -> None:
    config = load_runtime_config()
    clock = SystemClock()
    engine = create_database_engine(config.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    deepseek = DeepSeekStructuredAdapter(config.deepseek)
    ollama = OllamaEmbeddingAdapter(config.ollama)
    inbox = InboxService(SqlInboxRepository(sessions))
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
        AuditService(SqlAuditRepository(sessions)),
    )
    agenda = AgendaService(SqlAgendaRepository(sessions))
    reminders = ReminderService(SqlReminderRepository(sessions))
    actions = ActionService(
        SqlActionRepository(sessions),
        agenda,
        reminders,
        clock,
        AuditService(SqlAuditRepository(sessions)),
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
    candidate_queries = CandidateQueryService(SqlCandidateRepository(sessions))
    scheduling = SchedulingService(
        candidate_queries,
        preferences,
        agenda,
        SqlProposalRepository(sessions),
        clock,
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
    rag = RetrievalAnswerService(
        retrieval,
        AIGatewayService(
            deepseek,
            SqlInvocationRepository(sessions),
            clock,
            config.deepseek.max_concurrency,
        ),
        config.rag_retrieval_limit,
    )
    router = QqCommandRouter(
        inbox,
        inbox,
        NormalizationService(SqlNormalizedContentRepository(sessions)),
        scheduling,
        candidate_queries,
        actions,
        agenda,
        agenda,
        reminders,
        SqlJobQueue(sessions),
        clock,
        config.schedule.default_reminder_minutes,
        rag,
        deletion,
    )
    gateway = OfficialQqGateway(config.qq, config.owner, router, clock)
    notifications = NotificationService(gateway, SqlDeliveryRepository(sessions), clock)
    reminder_worker = ReminderWorker(
        reminders,
        agenda,
        notifications,
        clock,
        "qq-reminders",
    )
    proposal_notifications = ProposalNotificationWorker(scheduling, notifications)
    gateway_task = asyncio.create_task(gateway.run_forever())
    try:
        await gateway.wait_ready()
        while True:
            await proposal_notifications.run_once()
            await reminder_worker.run_once()
            await asyncio.sleep(5)
    finally:
        gateway_task.cancel()
        await asyncio.gather(gateway_task, return_exceptions=True)
        await ollama.close()
        await deepseek.close()
        await engine.dispose()


def main() -> None:
    configure_event_loop_policy()
    configure_logging()
    asyncio.run(run_qq())
