"""QQ long-connection process composition root."""

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker

from qq_time_agent.adapters.inbound.qq.commands import QqCommandRouter
from qq_time_agent.adapters.inbound.qq.gateway import OfficialQqGateway
from qq_time_agent.adapters.inbound.workers.reminders import ReminderWorker
from qq_time_agent.adapters.outbound.ai.deepseek import DeepSeekStructuredAdapter
from qq_time_agent.adapters.outbound.ollama.embedding import OllamaEmbeddingAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.jobs import SqlJobQueue
from qq_time_agent.bootstrap.logging import configure_logging
from qq_time_agent.bootstrap.qq_notifications import build_qq_notification_services
from qq_time_agent.bootstrap.runtime import configure_event_loop_policy
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.contracts.tools import ToolDispatcher
from qq_time_agent.modules.actions.application.service import ActionService
from qq_time_agent.modules.actions.infrastructure.repository import SqlActionRepository
from qq_time_agent.modules.agenda.application.notification_query import (
    AgendaNotificationQueryService,
)
from qq_time_agent.modules.agenda.application.service import AgendaService
from qq_time_agent.modules.agenda.infrastructure.repository import SqlAgendaRepository
from qq_time_agent.modules.agent.application.budget import ContextBudgetPolicy
from qq_time_agent.modules.agent.application.context import AgentContextAssembler
from qq_time_agent.modules.agent.application.json_model import JsonAgentModel
from qq_time_agent.modules.agent.application.loop import AgentLoop, AgentLoopConfig
from qq_time_agent.modules.agent.application.run_service import AgentRunService
from qq_time_agent.modules.agent.infrastructure.repository import SqlAgentRunRepository
from qq_time_agent.modules.ai_gateway.application.service import AIGatewayService
from qq_time_agent.modules.ai_gateway.infrastructure.repository import SqlInvocationRepository
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.calendar_system.application.authorization import (
    OwnerCalendarAuthorization,
)
from qq_time_agent.modules.calendar_system.application.tools import CalendarToolRegistry
from qq_time_agent.modules.identity.application.aliases import OwnerGroupAliasService
from qq_time_agent.modules.identity.application.service import UserPreferencesService
from qq_time_agent.modules.identity.application.tools import OwnerGroupAliasToolRegistry
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.identity.infrastructure.repository import (
    SqlOwnerGroupAliasRepository,
    SqlUserPreferencesRepository,
)
from qq_time_agent.modules.inbox.application.asset_discovery import MailAssetDiscoveryService
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.infrastructure.asset_repository import SqlSourceAssetRepository
from qq_time_agent.modules.inbox.infrastructure.repository import SqlInboxRepository
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository
from qq_time_agent.modules.normalization.application.service import NormalizationService
from qq_time_agent.modules.normalization.infrastructure.repository import (
    SqlNormalizedContentRepository,
)
from qq_time_agent.modules.reminders.application.service import ReminderService
from qq_time_agent.modules.reminders.infrastructure.repository import SqlReminderRepository
from qq_time_agent.modules.retrieval.application.service import HybridRetrievalService
from qq_time_agent.modules.scheduling.application.pending_query import PendingProposalQueryService
from qq_time_agent.modules.scheduling.infrastructure.repository import SqlProposalRepository


async def run_qq() -> None:
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
    inbox = InboxService(SqlInboxRepository(sessions))
    knowledge_repository = SqlKnowledgeRepository(sessions)
    agenda_repository = SqlAgendaRepository(sessions)
    agenda = AgendaService(agenda_repository)
    reminders = ReminderService(SqlReminderRepository(sessions))
    actions = ActionService(
        SqlActionRepository(sessions),
        agenda,
        reminders,
        clock,
        AuditService(SqlAuditRepository(sessions)),
        agenda,
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
    model = AIGatewayService(
        deepseek,
        SqlInvocationRepository(sessions),
        clock,
        config.deepseek.max_concurrency,
    )
    retrieval.configure_query_model(model)
    tools = ToolDispatcher(
        CalendarToolRegistry(
            agenda, actions, OwnerCalendarAuthorization("owner"), str(config.schedule.timezone)
        ),
        OwnerGroupAliasToolRegistry(owner_aliases),
    )
    agent = AgentLoop(
        JsonAgentModel(
            model,
            max_context_tokens=config.agent_context.max_context_tokens,
            safety_margin_tokens=config.agent_context.safety_margin_tokens,
        ),
        tools,
        config=AgentLoopConfig(
            model_output_token_budget=config.agent_context.model_output_token_budget,
            max_output_tokens_per_request=config.agent_context.max_output_tokens_per_request,
            observation_token_budget=config.agent_context.observation_tokens,
        ),
        owner_timezone=str(config.schedule.timezone),
        clock=clock,
    )
    agent_context = AgentContextAssembler(
        retrieval,
        inbox,
        SqlAgentRunRepository(sessions),
        SqlInboxRepository(sessions),
        AgendaNotificationQueryService(agenda_repository),
        PendingProposalQueryService(SqlProposalRepository(sessions), clock),
        str(config.schedule.timezone),
        owner_aliases,
        budget=context_policy,
        retrieval_limit=config.agent_context.retrieval_limit,
        history_limit=config.agent_context.history_limit,
    )
    agent_runs = AgentRunService(SqlAgentRunRepository(sessions), agent, clock)
    router = QqCommandRouter(
        inbox,
        inbox,
        NormalizationService(SqlNormalizedContentRepository(sessions)),
        queue,
        clock,
        MailAssetDiscoveryService(
            SqlSourceAssetRepository(sessions), queue, config.assets.raw_retention_hours
        ),
        agent_context,
        agent_runs,
        config.qq.display_name,
    )
    gateway = OfficialQqGateway(config.qq, config.owner, router, clock)
    notifications, intent_delivery = build_qq_notification_services(
        sessions, preferences, agenda_repository, gateway, clock, str(config.schedule.timezone)
    )
    reminder_worker = ReminderWorker(
        reminders,
        agenda,
        notifications,
        clock,
        "qq-reminders",
    )
    gateway_task = asyncio.create_task(gateway.run_forever())
    try:
        await gateway.wait_ready()
        while True:
            await reminder_worker.run_once()
            await intent_delivery.run_once(clock.now())
            await asyncio.sleep(5)
    finally:
        gateway_task.cancel()
        await asyncio.gather(gateway_task, return_exceptions=True)
        await ollama.close()
        await deepseek.close()
        await engine.dispose()


def main() -> None:
    configure_event_loop_policy()
    configure_logging(role="qq")
    asyncio.run(run_qq())
