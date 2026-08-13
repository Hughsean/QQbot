"""Explicit real QQ Mail read-only sync without privacy-bearing output."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.adapters.outbound.qq_mail.imap import QqMailImapAdapter
from qq_time_agent.bootstrap.settings import load_qq_mail_sandbox_config, load_runtime_config
from qq_time_agent.contracts.source import SourceType
from qq_time_agent.modules.connections.contracts import MailAccessGrant
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.inbox.application.service import InboxService
from qq_time_agent.modules.inbox.application.sync import MailSyncService
from qq_time_agent.modules.inbox.infrastructure.repository import SqlInboxRepository
from qq_time_agent.modules.inbox.infrastructure.tables import (
    InboxConnectionStateRow,
    InboxItemRow,
    InboxRawContentRow,
    InboxSourceDeletionRow,
    InboxSyncCursorRow,
)
from qq_time_agent.modules.normalization.application.service import NormalizationService
from qq_time_agent.modules.normalization.infrastructure.repository import (
    SqlNormalizedContentRepository,
)
from qq_time_agent.modules.normalization.infrastructure.tables import NormalizedContentRow

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class SandboxConnection:
    grant: MailAccessGrant
    completed_at: datetime | None = None

    async def acquire_mail_access(self, connection_id: UUID) -> MailAccessGrant:
        assert connection_id == self.grant.connection_id
        return self.grant

    async def ensure_sync_available(self, connection_id: UUID) -> None:
        assert connection_id == self.grant.connection_id

    async def mark_sync_succeeded(self, connection_id: UUID, completed_at: datetime) -> None:
        assert connection_id == self.grant.connection_id
        self.completed_at = completed_at

    async def mark_sync_reauth_required(self, connection_id: UUID) -> None:
        raise AssertionError("real QQ Mail sandbox authentication unexpectedly failed")

    async def mark_sync_degraded(self, connection_id: UUID) -> None:
        raise AssertionError("real QQ Mail sandbox unexpectedly degraded")


async def test_real_qq_mail_tls_readonly_two_round_incremental_sync() -> None:
    sandbox = load_qq_mail_sandbox_config()
    runtime = load_runtime_config()
    address = sandbox.address.get_secret_value()
    clock = Clock()
    adapter = QqMailImapAdapter(runtime.qq_mail, clock)
    engine = create_database_engine(runtime.database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    connection_id = uuid4()
    credential = CredentialHandle(
        sandbox.authorization_code.get_secret_value(), CredentialKind.IMAP_AUTH_CODE, None
    )
    connection = SandboxConnection(MailAccessGrant(connection_id, "owner", address, credential))
    repository = SqlInboxRepository(sessions)
    service = MailSyncService(
        connection,
        InboxService(repository),
        repository,
        NormalizationService(SqlNormalizedContentRepository(sessions)),
        adapter,
        clock,
        runtime.mail_initial_lookback_days,
        source_type=SourceType.QQ_MAIL,
    )
    try:
        await adapter.verify(address, sandbox.authorization_code)
        first = await service.synchronize(connection_id)
        count_after_first = await _item_count(sessions, connection_id)
        second = await service.synchronize(connection_id)
        count_after_second = await _item_count(sessions, connection_id)

        assert first.round_complete and second.round_complete
        assert first.pages >= 1 and second.pages >= 1
        assert count_after_first == first.created
        assert second.created == 0
        assert count_after_second == count_after_first
        assert connection.completed_at is not None
    finally:
        await _delete_sandbox_rows(sessions, connection_id)
        await adapter.close()
        await engine.dispose()


async def _item_count(sessions: async_sessionmaker[AsyncSession], connection_id: UUID) -> int:
    async with sessions() as session:
        value = await session.scalar(
            select(func.count())
            .select_from(InboxItemRow)
            .where(InboxItemRow.connection_id == connection_id)
        )
        return int(value or 0)


async def _delete_sandbox_rows(
    sessions: async_sessionmaker[AsyncSession], connection_id: UUID
) -> None:
    async with sessions.begin() as session:
        items = tuple(
            await session.scalars(
                select(InboxItemRow).where(InboxItemRow.connection_id == connection_id)
            )
        )
        item_ids = tuple(item.inbox_item_id for item in items)
        raw_ids = tuple(item.raw_content_ref for item in items)
        if item_ids:
            await session.execute(
                delete(NormalizedContentRow).where(NormalizedContentRow.inbox_item_id.in_(item_ids))
            )
            await session.execute(
                delete(InboxItemRow).where(InboxItemRow.inbox_item_id.in_(item_ids))
            )
            await session.execute(
                delete(InboxRawContentRow).where(InboxRawContentRow.raw_content_id.in_(raw_ids))
            )
        await session.execute(
            delete(InboxSyncCursorRow).where(InboxSyncCursorRow.connection_id == connection_id)
        )
        await session.execute(
            delete(InboxSourceDeletionRow).where(
                InboxSourceDeletionRow.connection_id == connection_id
            )
        )
        await session.execute(
            delete(InboxConnectionStateRow).where(
                InboxConnectionStateRow.connection_id == connection_id
            )
        )
