"""Worker-only composition for external mail connection services."""

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.outbound.microsoft_graph.connection import (
    MicrosoftGraphConnectionAdapter,
)
from qq_time_agent.adapters.outbound.microsoft_graph.mail import MicrosoftGraphMailAdapter
from qq_time_agent.adapters.outbound.qq_mail.imap import QqMailImapAdapter
from qq_time_agent.bootstrap.config_models import RuntimeConfig
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.connections.application.cleanup_ports import (
    ConnectionJobCancellationPort,
)
from qq_time_agent.modules.connections.application.oauth import MicrosoftConnectionService
from qq_time_agent.modules.connections.application.qq_mail import QqMailConnectionService
from qq_time_agent.modules.connections.infrastructure.fingerprints import HmacAccountFingerprinter
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.credentials.application.vault import VaultService
from qq_time_agent.modules.credentials.infrastructure.cipher import AesGcmCredentialCipher
from qq_time_agent.modules.credentials.infrastructure.repository import SqlCredentialRepository
from qq_time_agent.modules.inbox.application.connection_deletion import (
    ConnectionSourceDeletionService,
)


class WorkerJobQueue(JobQueue, ConnectionJobCancellationPort, Protocol):
    pass


@dataclass(frozen=True, slots=True)
class WorkerMailConnections:
    microsoft: MicrosoftConnectionService
    qq: QqMailConnectionService
    graph_connection: MicrosoftGraphConnectionAdapter
    graph_mail: MicrosoftGraphMailAdapter
    qq_mail: QqMailImapAdapter


def build_worker_mail_connections(
    config: RuntimeConfig,
    sessions: async_sessionmaker[AsyncSession],
    jobs: WorkerJobQueue,
    source_deletion: ConnectionSourceDeletionService,
    audit: AuditService,
    clock: Clock,
) -> WorkerMailConnections:
    repository = SqlConnectionRepository(sessions)
    fingerprinter = HmacAccountFingerprinter(config.credential_encryption_key)
    vault = VaultService(
        SqlCredentialRepository(sessions),
        AesGcmCredentialCipher(config.credential_encryption_key),
        clock,
    )
    graph_connection = MicrosoftGraphConnectionAdapter(config.microsoft, clock)
    graph_mail = MicrosoftGraphMailAdapter(clock, max_attachment_bytes=config.assets.max_bytes)
    microsoft = MicrosoftConnectionService(
        repository,
        vault,
        graph_connection,
        clock,
        fingerprinter,
        jobs,
        source_deletion,
        audit=audit,
    )
    qq_mail = QqMailImapAdapter(config.qq_mail, clock, max_attachment_bytes=config.assets.max_bytes)
    qq = QqMailConnectionService(
        repository,
        vault,
        qq_mail,
        jobs,
        source_deletion,
        clock,
        fingerprinter,
        audit,
    )
    return WorkerMailConnections(microsoft, qq, graph_connection, graph_mail, qq_mail)
