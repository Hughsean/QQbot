from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.notifications.application.ports import StoredSuppression
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntentDraft,
    NotificationIntentState,
    NotificationKind,
)
from qq_time_agent.modules.notifications.infrastructure.repository import (
    SqlNotificationIntentRepository,
    SqlSuppressionRepository,
)
from qq_time_agent.modules.notifications.infrastructure.tables import (
    NotificationIntentRow,
    ReminderSuppressionRow,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
NOW = datetime(2026, 8, 15, 8, tzinfo=UTC)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


def _draft(key: str) -> NotificationIntentDraft:
    return NotificationIntentDraft(
        "owner",
        NotificationKind.DAILY_DIGEST,
        "daily-digest:owner",
        key,
        "notification-v1",
        "2026-08-15 日程摘要",
        NOW,
    )


async def test_intent_upsert_lease_cooldown_and_expired_recovery(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlNotificationIntentRepository(sessions)
    first = await repository.add_or_get(_draft("intent-integration-1"), NOW)
    duplicate = await repository.add_or_get(_draft("intent-integration-1"), NOW)
    assert duplicate.intent_id == first.intent_id

    leased = await repository.lease_due(NOW, "qq-1", timedelta(seconds=30), 10)
    assert [value.intent_id for value in leased] == [first.intent_id]
    assert await repository.lease_due(NOW, "qq-2", timedelta(seconds=30), 10) == ()
    expected = leased[0].version
    leased[0].mark_sent("delivery-1", NOW + timedelta(seconds=1))
    await repository.save(leased[0], expected)
    assert await repository.has_recent_sent("daily-digest:owner", NOW - timedelta(hours=24))

    second = await repository.add_or_get(_draft("intent-integration-2"), NOW)
    leased_second = await repository.lease_due(NOW, "qq-1", timedelta(seconds=1), 10)
    assert leased_second[0].intent_id == second.intent_id
    assert await repository.recover_expired(NOW + timedelta(seconds=2), 10) == 1
    async with sessions() as session:
        row = await session.get(NotificationIntentRow, second.intent_id)
        assert row is not None and row.state == NotificationIntentState.AMBIGUOUS.value
    assert await repository.has_open("daily-digest:owner")
    blocked = await repository.add_or_get(_draft("intent-integration-3"), NOW)
    assert blocked.intent_id == second.intent_id

    async with sessions.begin() as session:
        await session.execute(
            delete(NotificationIntentRow).where(
                NotificationIntentRow.idempotency_key.in_(
                    (
                        "intent-integration-1",
                        "intent-integration-2",
                        "intent-integration-3",
                    )
                )
            )
        )


async def test_reminder_suppression_is_idempotently_persisted(engine: AsyncEngine) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlSuppressionRepository(sessions)
    key = "reminder:integration:suppression"
    try:
        first = await repository.record(StoredSuppression(key, "verified_completed", NOW))
        repeated = await repository.record(
            StoredSuppression(key, "different_reason", NOW + timedelta(seconds=1))
        )
        assert repeated == first
        assert await repository.get(key) == first
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ReminderSuppressionRow).where(ReminderSuppressionRow.idempotency_key == key)
            )
