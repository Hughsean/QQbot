"""Worker-only composition for source asset processing services."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.outbound.qq.media import OfficialQqMediaRoute
from qq_time_agent.bootstrap.config_models import AssetConfig
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.jobs import JobQueue
from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.connections.contracts import ConnectionSyncPort
from qq_time_agent.modules.inbox.application.asset_cleanup import SourceAssetCleanupService
from qq_time_agent.modules.inbox.application.asset_discovery import MailAssetDiscoveryService
from qq_time_agent.modules.inbox.application.asset_fetch import (
    MailAssetRoute,
    SourceAssetFetchService,
)
from qq_time_agent.modules.inbox.application.asset_parse import SourceAssetParseService
from qq_time_agent.modules.inbox.contracts import MailProvider
from qq_time_agent.modules.inbox.infrastructure.asset_repository import SqlSourceAssetRepository
from qq_time_agent.modules.inbox.infrastructure.blob_store import FileAssetBlobStore
from qq_time_agent.modules.normalization.infrastructure.asset_repository import (
    SqlNormalizedAssetRepository,
)
from qq_time_agent.modules.normalization.infrastructure.document_parser import DocumentAssetParser
from qq_time_agent.modules.normalization.infrastructure.icalendar_parser import IcalendarParser


@dataclass(frozen=True, slots=True)
class WorkerAssetServices:
    discovery: MailAssetDiscoveryService
    fetch: SourceAssetFetchService
    parse: SourceAssetParseService
    cleanup: SourceAssetCleanupService
    normalized: SqlNormalizedAssetRepository
    qq_media: OfficialQqMediaRoute


def build_worker_asset_services(
    config: AssetConfig,
    owner_timezone: str,
    sessions: async_sessionmaker[AsyncSession],
    jobs: JobQueue,
    microsoft_connections: ConnectionSyncPort,
    qq_connections: ConnectionSyncPort,
    microsoft_mail: MailProvider,
    qq_mail: MailProvider,
    clock: Clock,
) -> WorkerAssetServices:
    repository = SqlSourceAssetRepository(sessions)
    blobs = FileAssetBlobStore(config.storage_path, config.max_bytes)
    normalized = SqlNormalizedAssetRepository(sessions)
    discovery = MailAssetDiscoveryService(repository, jobs, config.raw_retention_hours)
    qq_media = OfficialQqMediaRoute(config.max_bytes)
    fetch = SourceAssetFetchService(
        repository,
        blobs,
        jobs,
        {
            SourceType.MICROSOFT_MAIL: MailAssetRoute(microsoft_connections, microsoft_mail),
            SourceType.QQ_MAIL: MailAssetRoute(qq_connections, qq_mail),
            SourceType.QQ_DIRECT: qq_media,
            SourceType.QQ_FORWARD: qq_media,
        },
        config.max_bytes,
    )
    parser = DocumentAssetParser(
        IcalendarParser(),
        config.max_pdf_pages,
        config.max_image_pixels,
        config.max_output_chars,
        config.processing_timeout_seconds,
    )
    parse = SourceAssetParseService(repository, blobs, parser, normalized, jobs, owner_timezone)
    return WorkerAssetServices(
        discovery,
        fetch,
        parse,
        SourceAssetCleanupService(repository, blobs, clock),
        normalized,
        qq_media,
    )
