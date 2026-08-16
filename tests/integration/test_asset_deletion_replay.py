from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.infrastructure.repository import SqlAuditRepository
from qq_time_agent.modules.audit.infrastructure.tables import AuditEventRow
from qq_time_agent.modules.data_lifecycle.application.coordinator import DeletionCoordinator
from qq_time_agent.modules.data_lifecycle.infrastructure.repository import SqlTombstoneRepository
from qq_time_agent.modules.data_lifecycle.infrastructure.tables import PurgeResultRow, TombstoneRow
from qq_time_agent.modules.inbox.application.asset_cleanup import SourceAssetCleanupService
from qq_time_agent.modules.inbox.domain.assets import AssetKind, SourceAsset
from qq_time_agent.modules.inbox.infrastructure.asset_repository import SqlSourceAssetRepository
from qq_time_agent.modules.inbox.infrastructure.blob_store import FileAssetBlobStore
from qq_time_agent.modules.inbox.infrastructure.purge import InboxPurgeAdapter
from qq_time_agent.modules.inbox.infrastructure.tables import InboxItemRow, InboxRawContentRow
from qq_time_agent.modules.knowledge.application.ports import IndexedChunk, IndexedSource
from qq_time_agent.modules.knowledge.infrastructure.purge import KnowledgePurgeAdapter
from qq_time_agent.modules.knowledge.infrastructure.repository import SqlKnowledgeRepository
from qq_time_agent.modules.knowledge.infrastructure.tables import KnowledgeSourceRow
from qq_time_agent.modules.normalization.infrastructure.asset_repository import (
    SqlNormalizedAssetRepository,
)
from qq_time_agent.modules.normalization.infrastructure.purge import NormalizationPurgeAdapter
from qq_time_agent.modules.normalization.infrastructure.tables import NormalizedAssetRow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
NOW = datetime(2026, 8, 20, tzinfo=UTC)
CLEANUP_NOW = NOW + timedelta(hours=2)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


class Clock:
    def now(self) -> datetime:
        return CLEANUP_NOW


async def test_asset_blob_and_derived_content_are_removed_before_tombstone_replay(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_ref = f"qq-mail:{uuid4()}:restore-{uuid4()}"
    blobs = FileAssetBlobStore(tmp_path, 1024)
    assets = SqlSourceAssetRepository(sessions)
    knowledge = SqlKnowledgeRepository(sessions)
    coordinator = DeletionCoordinator(
        SqlTombstoneRepository(sessions, Clock()),
        (
            KnowledgePurgeAdapter(knowledge),
            NormalizationPurgeAdapter(sessions),
            InboxPurgeAdapter(sessions),
        ),
        Clock(),
        timedelta(hours=24),
        AuditService(SqlAuditRepository(sessions)),
    )
    cleanup = SourceAssetCleanupService(assets, blobs, Clock())
    tombstone = None
    try:
        first_asset, first_key = await _restore_asset_source(
            sessions, assets, blobs, knowledge, source_ref
        )
        assert await cleanup.cleanup_expired() == 1
        with pytest.raises(FileNotFoundError):
            await blobs.read(first_key)
        tombstone = await coordinator.record_deletion(source_ref)
        await _assert_absent(sessions, source_ref, first_asset)

        replay_asset, replay_key = await _restore_asset_source(
            sessions, assets, blobs, knowledge, source_ref
        )
        assert await cleanup.cleanup_expired() == 1
        assert await coordinator.replay() >= 1
        with pytest.raises(FileNotFoundError):
            await blobs.read(replay_key)
        await _assert_absent(sessions, source_ref, replay_asset)
    finally:
        await KnowledgePurgeAdapter(knowledge).purge_subject(source_ref, uuid4())
        await NormalizationPurgeAdapter(sessions).purge_subject(source_ref, uuid4())
        await InboxPurgeAdapter(sessions).purge_subject(source_ref, uuid4())
        async with sessions.begin() as session:
            if tombstone is not None:
                await session.execute(
                    delete(PurgeResultRow).where(
                        PurgeResultRow.tombstone_id == tombstone.tombstone_id
                    )
                )
                await session.execute(
                    delete(TombstoneRow).where(TombstoneRow.tombstone_id == tombstone.tombstone_id)
                )
            await session.execute(
                delete(AuditEventRow).where(AuditEventRow.subject_ref == source_ref)
            )


async def _restore_asset_source(
    sessions: async_sessionmaker[AsyncSession],
    assets: SqlSourceAssetRepository,
    blobs: FileAssetBlobStore,
    knowledge: SqlKnowledgeRepository,
    source_ref: str,
) -> tuple[UUID, str]:
    _, connection_text, external_id = source_ref.split(":", 2)
    item_id = uuid4()
    raw_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            InboxRawContentRow(
                raw_content_id=raw_id,
                subject="Attachment source",
                body_text="Synthetic body",
                body_html=None,
                mime_type="text/plain",
                recipients=[],
                internet_message_id=None,
                change_key=None,
                has_attachments=True,
                created_at=NOW,
            )
        )
        session.add(
            InboxItemRow(
                inbox_item_id=item_id,
                connection_id=UUID(connection_text),
                user_id="owner",
                source_type="QQ_MAIL",
                ingress_type="SYNC",
                trust_level="T2",
                external_id=external_id,
                dedupe_key=f"restore:{item_id}",
                thread_id=None,
                sender_id="synthetic@example.test",
                sender_display=None,
                occurred_at=NOW,
                received_at=NOW,
                raw_content_ref=raw_id,
                content_hash="a" * 64,
                status="COMPLETED",
                failure_class=None,
                retry_count=0,
                version=1,
                deleted_at=None,
            )
        )
    asset = await assets.add_or_get(
        SourceAsset.discover(
            item_id,
            f"part-{uuid4()}",
            "part:2",
            AssetKind.PDF,
            "application/pdf",
            NOW,
            NOW + timedelta(hours=1),
        )
    )
    receipt = await blobs.put(asset.asset_id, b"%PDF-synthetic")
    version = asset.version
    asset.mark_stored(
        detected_content_type="application/pdf",
        actual_size=receipt.byte_count,
        content_sha256=receipt.sha256,
        storage_key=receipt.storage_key,
        now=NOW,
    )
    await assets.save(asset, version)
    await SqlNormalizedAssetRepository(sessions).store_asset(
        asset.asset_id,
        item_id,
        "Attachment meeting text",
        receipt.sha256,
        "parser-v1",
        source_ref,
        None,
    )
    vector = (1.0,) + (0.0,) * 1023
    await knowledge.replace_active(
        IndexedSource(
            uuid4(),
            source_ref,
            "QQ_MAIL",
            "v1",
            NOW,
            "T2",
            {},
            "v1",
            "asset-replay-v1",
            "model",
            "digest",
            1024,
            (IndexedChunk(uuid4(), 0, "Attachment meeting text", "hash", vector),),
        )
    )
    return asset.asset_id, receipt.storage_key


async def _assert_absent(
    sessions: async_sessionmaker[AsyncSession], source_ref: str, asset_id: UUID
) -> None:
    async with sessions() as session:
        counts = (
            await session.scalar(
                select(func.count())
                .select_from(NormalizedAssetRow)
                .where(NormalizedAssetRow.asset_id == asset_id)
            ),
            await session.scalar(
                select(func.count())
                .select_from(KnowledgeSourceRow)
                .where(KnowledgeSourceRow.source_ref == source_ref)
            ),
            await session.scalar(
                select(func.count())
                .select_from(InboxItemRow)
                .where(
                    InboxItemRow.connection_id == UUID(source_ref.split(":", 2)[1]),
                    InboxItemRow.external_id == source_ref.split(":", 2)[2],
                )
            ),
        )
    assert counts == (0, 0, 0)
