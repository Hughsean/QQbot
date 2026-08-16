"""Explicit live Mail.Read verification without exposing mailbox content."""

from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from qq_time_agent.adapters.outbound.microsoft_graph.connection import (
    MicrosoftGraphConnectionAdapter,
)
from qq_time_agent.adapters.outbound.microsoft_graph.mail import MicrosoftGraphMailAdapter
from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.modules.connections.application.oauth import MicrosoftConnectionService
from qq_time_agent.modules.connections.infrastructure.fingerprints import HmacAccountFingerprinter
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher
from qq_time_agent.modules.credentials.infrastructure.repository import SqlCredentialRepository
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.application.sync import MailSyncService
from qq_time_agent.modules.inbox.infrastructure.repository import SqlInboxRepository
from qq_time_agent.modules.normalization.application.service import NormalizationService
from qq_time_agent.modules.normalization.infrastructure.repository import (
    SqlNormalizedContentRepository,
)

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]


class SyncOnlyCleanup:
    async def cancel_pending_for_connection(
        self, connection_id: UUID, cancelled_at: datetime
    ) -> int:
        raise AssertionError("live sync sandbox must not disconnect connections")

    async def allow_connection_sources(self, connection_id: UUID) -> None:
        return None

    async def block_connection_sources(self, connection_id: UUID) -> None:
        raise AssertionError("live sync sandbox must not block connection sources")

    async def delete_connection_sources(self, connection_id: UUID) -> int:
        raise AssertionError("live sync sandbox must not delete connection sources")


async def test_live_mail_read_incremental_sync_is_restart_safe() -> None:
    config = load_runtime_config()
    clock = SystemClock()
    engine = create_database_engine(config.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    graph_connection = MicrosoftGraphConnectionAdapter(config.microsoft, clock)
    graph_mail = MicrosoftGraphMailAdapter(clock)
    connections = MicrosoftConnectionService(
        SqlConnectionRepository(sessions),
        VaultService(
            SqlCredentialRepository(sessions),
            AesGcmCredentialCipher(config.credential_encryption_key),
            clock,
        ),
        graph_connection,
        clock,
        HmacAccountFingerprinter(config.credential_encryption_key),
        SyncOnlyCleanup(),
        SyncOnlyCleanup(),
    )
    repository = SqlInboxRepository(sessions)
    service = MailSyncService(
        connections,
        InboxService(repository),
        repository,
        NormalizationService(SqlNormalizedContentRepository(sessions)),
        graph_mail,
        clock,
        config.mail_initial_lookback_days,
    )
    try:
        connection = await connections.status("owner")
        assert connection is not None and connection.status == "ACTIVE", (
            "Microsoft owner connection must be ACTIVE before the live mail sandbox test"
        )
        first = await service.synchronize(connection.connection_id)
        second = await service.synchronize(connection.connection_id)
        assert first.round_complete and second.round_complete
        assert first.pages >= 1 and second.pages >= 1
        refreshed = await connections.status("owner")
        assert refreshed is not None and refreshed.last_synced_at is not None
    finally:
        await graph_mail.close()
        await graph_connection.close()
        await engine.dispose()
