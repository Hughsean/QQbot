from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.inbox.domain.assets import AssetKind, SourceAsset
from qq_time_agent.modules.inbox.infrastructure.asset_repository import (
    InboxParentUnavailableError,
    SqlSourceAssetRepository,
)
from qq_time_agent.modules.inbox.infrastructure.tables import InboxItemRow, InboxSourceAssetRow
from qq_time_agent.modules.normalization.contracts import CalendarParseResult
from qq_time_agent.modules.normalization.infrastructure.asset_repository import (
    SqlNormalizedAssetRepository,
)
from qq_time_agent.modules.normalization.infrastructure.purge import NormalizationPurgeAdapter

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_type", "source_prefix"),
    (("QQ_MAIL", "qq-mail"), ("QQ_DIRECT", "qq")),
)
async def test_asset_persistence_is_idempotent_and_parent_fenced(
    engine: AsyncEngine, source_type: str, source_prefix: str
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlSourceAssetRepository(sessions)
    now = datetime(2026, 8, 14, tzinfo=UTC)
    parent_id = uuid4()
    connection_id = uuid4()
    parent = InboxItemRow(
        inbox_item_id=parent_id,
        connection_id=connection_id,
        user_id="integration-owner",
        source_type=source_type,
        ingress_type="SYNC",
        trust_level="T2",
        external_id=str(uuid4()),
        dedupe_key=str(uuid4()),
        thread_id=None,
        sender_id="sender",
        sender_display=None,
        occurred_at=now,
        received_at=now,
        raw_content_ref=uuid4(),
        content_hash="a" * 64,
        status="RECEIVED",
        failure_class=None,
        retry_count=0,
        version=1,
        deleted_at=None,
    )
    async with sessions.begin() as session:
        session.add(parent)

    asset = SourceAsset.discover(
        parent_id,
        "part-2",
        "part:2",
        AssetKind.PDF,
        "application/pdf",
        now,
        now + timedelta(hours=24),
        transfer_encoding="base64",
    )
    try:
        first = await repository.add_or_get(asset)
        duplicate = SourceAsset.discover(
            parent_id,
            "part-2",
            "part:2",
            AssetKind.PDF,
            "application/pdf",
            now,
            now + timedelta(hours=24),
            transfer_encoding="base64",
        )
        second = await repository.add_or_get(duplicate)
        assert first.asset_id == second.asset_id
        context = await repository.get_context(first.asset_id)
        assert context is not None
        assert context.asset.transfer_encoding == "base64"
        assert context.source_ref is not None
        assert context.source_ref.startswith(f"{source_prefix}:{connection_id}:")

        normalized = SqlNormalizedAssetRepository(sessions)
        await normalized.store_asset(
            first.asset_id,
            parent_id,
            "Normalized attachment text",
            "b" * 64,
            "parser-v1",
            context.source_ref,
            CalendarParseResult("REQUEST", ()),
        )
        stored = await normalized.get_asset(first.asset_id)
        assert stored is not None and stored.calendar is not None
        assert await normalized.list_assets(parent_id) == (stored,)
        result = await NormalizationPurgeAdapter(sessions).purge_subject(
            context.source_ref, uuid4()
        )
        assert result.deleted_count == 1
        assert await normalized.get_asset(first.asset_id) is None

        async with sessions.begin() as session:
            stored_parent = await session.get(InboxItemRow, parent_id, with_for_update=True)
            assert stored_parent is not None
            stored_parent.deleted_at = now

        blocked = SourceAsset.discover(
            parent_id,
            "part-3",
            "part:3",
            AssetKind.ICS,
            "text/calendar",
            now,
            now + timedelta(hours=24),
        )
        with pytest.raises(InboxParentUnavailableError):
            await repository.add_or_get(blocked)
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(InboxItemRow).where(InboxItemRow.inbox_item_id == parent_id)
            )
        async with sessions() as session:
            assert await session.get(InboxSourceAssetRow, asset.asset_id) is None
