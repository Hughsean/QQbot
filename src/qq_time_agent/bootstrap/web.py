"""Web process entry point and dependency composition."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.inbound.http.app import create_app
from qq_time_agent.adapters.inbound.http.health import ReadinessService
from qq_time_agent.adapters.inbound.http.mail_sync import mail_sync_router
from qq_time_agent.adapters.inbound.http.metrics import MetricsService, metrics_router
from qq_time_agent.adapters.inbound.http.microsoft_oauth import microsoft_oauth_router
from qq_time_agent.adapters.inbound.http.owner_session import OwnerSessionSigner
from qq_time_agent.adapters.outbound.microsoft_graph.connection import (
    MicrosoftGraphConnectionAdapter,
)
from qq_time_agent.adapters.outbound.ollama.embedding import OllamaEmbeddingAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.persistence.health import DatabaseReadinessProbe
from qq_time_agent.adapters.outbound.persistence.jobs import SqlJobQueue
from qq_time_agent.adapters.outbound.persistence.metrics import SqlMetricsSnapshot
from qq_time_agent.bootstrap.logging import configure_logging
from qq_time_agent.bootstrap.runtime import configure_event_loop_policy
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.connections.application.oauth import MicrosoftConnectionService
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher
from qq_time_agent.modules.credentials.infrastructure.repository import SqlCredentialRepository
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.infrastructure.repository import SqlInboxRepository


def build_app() -> tuple[FastAPI, AsyncEngine, tuple[object, ...]]:
    config = load_runtime_config()
    clock = SystemClock()
    engine = create_database_engine(config.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    embeddings = OllamaEmbeddingAdapter(config.ollama)
    graph = MicrosoftGraphConnectionAdapter(config.microsoft, clock)
    vault = VaultService(
        SqlCredentialRepository(sessions),
        AesGcmCredentialCipher(config.credential_encryption_key),
        clock,
    )
    connections = MicrosoftConnectionService(
        SqlConnectionRepository(sessions),
        vault,
        graph,
        clock,
        audit=AuditService(SqlAuditRepository(sessions)),
    )
    oauth = microsoft_oauth_router(
        connections,
        OwnerSessionSigner(config.app.signing_key, clock),
    )
    readiness = ReadinessService(DatabaseReadinessProbe(engine), embeddings)
    inbox = InboxService(SqlInboxRepository(sessions))
    sync = mail_sync_router(
        connections,
        inbox,
        SqlJobQueue(sessions),
        OwnerSessionSigner(config.app.signing_key, clock),
        clock,
        config.mail_sync_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await embeddings.close()
            await graph.close()
            await engine.dispose()

    app = create_app(
        readiness,
        lifespan,
        (oauth, sync, metrics_router(MetricsService(SqlMetricsSnapshot(sessions)))),
    )
    return app, engine, (embeddings, graph)


def main() -> None:
    configure_event_loop_policy()
    configure_logging()
    config = load_runtime_config()
    app, _, _ = build_app()
    uvicorn.run(
        app,
        host=config.app.listen_host,
        port=config.app.listen_port,
        access_log=False,
        loop="none",
    )
