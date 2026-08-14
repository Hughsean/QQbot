"""Offline post-restore tombstone replay gate."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.logging import configure_logging
from qq_time_agent.bootstrap.runtime import configure_event_loop_policy
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.data_lifecycle.application.coordinator import DeletionCoordinator
from qq_time_agent.modules.data_lifecycle.infrastructure.repository import SqlTombstoneRepository
from qq_time_agent.modules.inbox.infrastructure.purge import InboxPurgeAdapter
from qq_time_agent.modules.knowledge.infrastructure.purge import KnowledgePurgeAdapter
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository
from qq_time_agent.modules.normalization.infrastructure.purge import NormalizationPurgeAdapter
from qq_time_agent.modules.scheduling.infrastructure.purge import SchedulingPurgeAdapter
from qq_time_agent.modules.understanding.infrastructure.purge import UnderstandingPurgeAdapter
from qq_time_agent.modules.workflow.infrastructure.purge import WorkflowPurgeAdapter

LOGGER = logging.getLogger(__name__)


async def replay_tombstones() -> int:
    config = load_runtime_config()
    clock = SystemClock()
    engine = create_database_engine(config.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    deletion = DeletionCoordinator(
        SqlTombstoneRepository(sessions, clock),
        (
            SchedulingPurgeAdapter(sessions),
            UnderstandingPurgeAdapter(sessions),
            WorkflowPurgeAdapter(sessions),
            KnowledgePurgeAdapter(SqlKnowledgeRepository(sessions)),
            NormalizationPurgeAdapter(sessions),
            InboxPurgeAdapter(sessions),
        ),
        clock,
        timedelta(hours=config.retention.source_deletion_hours),
        AuditService(SqlAuditRepository(sessions)),
    )
    try:
        LOGGER.info("tombstone replay started")
        count = await deletion.replay()
        LOGGER.info("tombstone replay completed", extra={"count": count})
        return count
    finally:
        await engine.dispose()


def main() -> None:
    configure_event_loop_policy()
    configure_logging(role="replay-tombstones")
    asyncio.run(replay_tombstones())
