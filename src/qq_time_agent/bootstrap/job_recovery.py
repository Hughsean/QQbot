"""Explicit recovery command for transient knowledge-index dead letters."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from qq_time_agent.adapters.outbound.ollama.embedding import OllamaEmbeddingAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.jobs import SqlJobQueue
from qq_time_agent.bootstrap.logging import configure_logging
from qq_time_agent.bootstrap.runtime import configure_event_loop_policy
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock

LOGGER = logging.getLogger(__name__)
KNOWLEDGE_JOB = "knowledge-index"


async def requeue_transient_knowledge_jobs() -> int:
    config = load_runtime_config()
    ollama = OllamaEmbeddingAdapter(config.ollama)
    try:
        health = await ollama.health()
        if not health.available:
            LOGGER.error(
                "knowledge dead letters were not requeued; embedding provider is unavailable",
                extra={"failure_class": health.failure_class},
            )
            raise RuntimeError("embedding provider must be ready before job recovery")
        engine = create_database_engine(config.database)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            count = await SqlJobQueue(sessions).requeue_transient_dead_letters(
                KNOWLEDGE_JOB, SystemClock().now()
            )
            LOGGER.info("transient knowledge dead letters requeued", extra={"count": count})
            return count
        finally:
            await engine.dispose()
    finally:
        await ollama.close()


def main() -> None:
    configure_event_loop_policy()
    configure_logging(role="requeue-knowledge-jobs")
    asyncio.run(requeue_transient_knowledge_jobs())
