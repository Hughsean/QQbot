from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.contracts import MailAddress, MailChange
from qq_time_agent.modules.inbox.infrastructure.repository import SqlInboxRepository
from qq_time_agent.modules.inbox.infrastructure.tables import (
    InboxItemRow,
    InboxRawContentRow,
    InboxSyncCursorRow,
)
from qq_time_agent.modules.normalization.infrastructure.tables import NormalizedContentRow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


def _mail(external_id: str) -> MailChange:
    return MailChange(
        external_id,
        "thread-1",
        "<message@example.test>",
        MailAddress("sender@example.test", "Sender"),
        (MailAddress("owner@example.test", "Owner"),),
        "Stage 3 integration",
        "Please review on Friday",
        "text",
        datetime(2026, 8, 12, tzinfo=UTC),
        "change-1",
        False,
    )


async def test_inbox_ingest_is_idempotent_traceable_and_cursor_is_owned(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlInboxRepository(sessions)
    service = InboxService(repository)
    connection_id = uuid4()
    external_id = f"integration-{uuid4()}"
    now = datetime(2026, 8, 13, tzinfo=UTC)
    first = await service.ingest_mail(connection_id, "owner", _mail(external_id), now)
    second = await service.ingest_mail(connection_id, "owner", _mail(external_id), now)
    assert first.created and not second.created
    assert first.inbox_item_id == second.inbox_item_id

    async with sessions() as session:
        item_count = await session.scalar(
            select(func.count())
            .select_from(InboxItemRow)
            .where(
                InboxItemRow.connection_id == connection_id,
                InboxItemRow.external_id == external_id,
            )
        )
        raw_count = await session.scalar(
            select(func.count())
            .select_from(InboxRawContentRow)
            .where(
                InboxRawContentRow.raw_content_id
                == select(InboxItemRow.raw_content_ref)
                .where(InboxItemRow.inbox_item_id == first.inbox_item_id)
                .scalar_subquery()
            )
        )
    assert item_count == raw_count == 1

    source = await service.source(first.inbox_item_id)
    assert source is not None
    assert source.sender_mask == "s***@example.test"
    assert source.external_id == external_id
    assert not source.deleted

    cursor = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=test"
    await repository.save_cursor(connection_id, cursor, now)
    assert await repository.get_cursor(connection_id) == cursor
    with pytest.raises(ValueError, match="Microsoft Graph"):
        await repository.save_cursor(connection_id, "https://evil.example/cursor", now)

    assert await repository.mark_deleted(connection_id, external_id, now)
    deleted = await service.source(first.inbox_item_id)
    assert deleted is not None and deleted.deleted
    assert await service.content(first.inbox_item_id) is None

    async with sessions.begin() as session:
        await session.execute(
            delete(NormalizedContentRow).where(
                NormalizedContentRow.inbox_item_id == first.inbox_item_id
            )
        )
        await session.execute(
            delete(InboxSyncCursorRow).where(InboxSyncCursorRow.connection_id == connection_id)
        )
        item = await session.get(InboxItemRow, first.inbox_item_id)
        if item is not None:
            raw_id = item.raw_content_ref
            await session.delete(item)
            raw = await session.get(InboxRawContentRow, raw_id)
            if raw is not None:
                await session.delete(raw)
