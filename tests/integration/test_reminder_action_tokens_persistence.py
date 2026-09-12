"""PostgreSQL checks for single-use Reminder interaction tokens."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.notifications.application.action_tokens import (
    ReminderActionTokenService,
)
from qq_time_agent.modules.notifications.infrastructure.tables import ReminderActionTokenRow

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
NOW = datetime(2026, 9, 13, 1, tzinfo=UTC)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


async def test_action_tokens_are_owner_bound_typed_expiring_and_mutually_exclusive(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    service = ReminderActionTokenService(sessions)
    reminder_id = uuid4()
    entry_id = uuid4()
    complete = await service.issue(
        owner_id="owner",
        reminder_id=reminder_id,
        agenda_entry_id=entry_id,
        agenda_entry_version=2,
        occurrence=1,
        action_type="reminder.complete",
        action_value=None,
        expires_at=NOW + timedelta(hours=24),
    )
    defer = await service.issue(
        owner_id="owner",
        reminder_id=reminder_id,
        agenda_entry_id=entry_id,
        agenda_entry_version=2,
        occurrence=1,
        action_type="reminder.defer",
        action_value="15m",
        expires_at=NOW + timedelta(hours=24),
    )

    assert await service.claim(complete, "intruder", "reminder.complete", NOW) is None
    assert await service.claim(complete, "owner", "reminder.defer", NOW) is None
    claimed = await service.claim(complete, "owner", "reminder.complete", NOW)
    assert claimed is not None
    assert claimed.reminder_id == reminder_id and claimed.agenda_entry_version == 2
    assert await service.claim(defer, "owner", "reminder.defer", NOW) is None
    assert await service.claim(complete, "owner", "reminder.complete", NOW) is None
    await service.resolve(claimed.token_hash, NOW, "SUCCEEDED")

    expired_reminder_id = uuid4()
    expired = await service.issue(
        owner_id="owner",
        reminder_id=expired_reminder_id,
        agenda_entry_id=entry_id,
        agenda_entry_version=2,
        occurrence=1,
        action_type="reminder.complete",
        action_value=None,
        expires_at=NOW,
    )
    assert await service.claim(expired, "owner", "reminder.complete", NOW) is None

    async with sessions.begin() as session:
        await session.execute(
            delete(ReminderActionTokenRow).where(
                ReminderActionTokenRow.reminder_id.in_((reminder_id, expired_reminder_id))
            )
        )
