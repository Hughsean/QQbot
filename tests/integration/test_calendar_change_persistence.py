from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.modules.normalization.contracts import CalendarChangeKind, CalendarEventView
from qq_time_agent.modules.understanding.domain.calendar_changes import (
    CalendarCandidateState,
    CalendarChangeCandidate,
)
from qq_time_agent.modules.understanding.domain.calendar_changes import (
    CalendarChangeKind as CandidateChangeKind,
)
from qq_time_agent.modules.understanding.infrastructure.calendar_fingerprints import (
    HmacCalendarEventFingerprinter,
)
from qq_time_agent.modules.understanding.infrastructure.calendar_repository import (
    SqlCalendarChangeRepository,
)
from qq_time_agent.modules.understanding.infrastructure.tables import CalendarChangeCandidateRow

pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 14, 8, tzinfo=UTC)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    value = create_database_engine(load_runtime_config().database)
    yield value
    await value.dispose()


def _candidate(
    fingerprinter: HmacCalendarEventFingerprinter,
    event_key: str,
    sequence: int,
) -> CalendarChangeCandidate:
    event = CalendarEventView(
        "not-persisted",
        sequence,
        CalendarChangeKind.UPSERT,
        "CONFIRMED",
        "Versioned review",
        NOW + timedelta(days=1),
        NOW + timedelta(days=1, hours=1),
        "UTC",
        False,
        None,
        (),
        None,
        (),
        (),
        None,
    )
    return CalendarChangeCandidate.create(
        uuid4(),
        uuid4(),
        event_key,
        fingerprinter.version_key(event_key, sequence),
        sequence,
        CandidateChangeKind.UPSERT,
        event.title,
        event.starts_at,
        event.ends_at,
        event.timezone,
        event.location,
        event.participants,
        event.recurrence_rule,
        CalendarCandidateState.PENDING_CREATE,
        None,
        "qq-mail:opaque-parent",
        NOW,
    )


@pytest.mark.asyncio
async def test_calendar_versions_are_idempotent_ordered_and_restart_safe(
    engine: AsyncEngine,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    repository = SqlCalendarChangeRepository(sessions)
    fingerprinter = HmacCalendarEventFingerprinter(
        SecretStr("integration-calendar-fingerprint-key")
    )
    event_key = fingerprinter.event_key("provider-event-uid", None)
    first = _candidate(fingerprinter, event_key, 1)
    second = _candidate(fingerprinter, event_key, 2)
    stale = _candidate(fingerprinter, event_key, 0)
    try:
        stored_first = await repository.add_version(first)
        duplicate = await repository.add_version(first)
        stored_second = await repository.add_version(second)
        stored_stale = await repository.add_version(stale)
        assert duplicate.candidate_id == stored_first.candidate_id
        assert stored_second.state is CalendarCandidateState.PENDING_CREATE
        assert stored_stale.state is CalendarCandidateState.STALE
        async with sessions() as session:
            rows = tuple(
                await session.scalars(
                    select(CalendarChangeCandidateRow)
                    .where(CalendarChangeCandidateRow.external_event_key == event_key)
                    .order_by(CalendarChangeCandidateRow.sequence)
                )
            )
        assert [row.state for row in rows] == ["STALE", "SUPERSEDED", "PENDING_CREATE"]
        assert all("provider-event-uid" not in repr(row.__dict__) for row in rows)
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(CalendarChangeCandidateRow).where(
                    CalendarChangeCandidateRow.external_event_key == event_key
                )
            )
