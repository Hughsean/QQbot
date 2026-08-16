from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr

from qq_time_agent.modules.agenda.contracts import AgendaEntryView
from qq_time_agent.modules.normalization.contracts import (
    CalendarChangeKind,
    CalendarEventView,
    CalendarParseResult,
)
from qq_time_agent.modules.understanding.application.calendar_ingestion import (
    CalendarChangeIngestionService,
)
from qq_time_agent.modules.understanding.domain.calendar_changes import (
    CalendarCandidateState,
    CalendarChangeCandidate,
)
from qq_time_agent.modules.understanding.infrastructure.calendar_fingerprints import (
    HmacCalendarEventFingerprinter,
)

NOW = datetime(2026, 8, 14, 8, tzinfo=UTC)


@dataclass
class Repository:
    values: list[CalendarChangeCandidate] = field(default_factory=list)

    async def add_version(self, candidate: CalendarChangeCandidate) -> CalendarChangeCandidate:
        self.values.append(candidate)
        return candidate


@dataclass
class Agenda:
    match: AgendaEntryView | None = None
    source_refs: list[str] = field(default_factory=list)

    async def find_by_source_ref(self, source_ref: str) -> AgendaEntryView | None:
        self.source_refs.append(source_ref)
        return self.match


def _event(kind: CalendarChangeKind, sequence: int = 0) -> CalendarEventView:
    return CalendarEventView(
        "provider-event-uid",
        sequence,
        kind,
        "CANCELLED" if kind is CalendarChangeKind.CANCEL else "CONFIRMED",
        "Project review",
        NOW + timedelta(days=1),
        NOW + timedelta(days=1, hours=1),
        "UTC",
        False,
        "Room 3",
        ("participant@example.test",),
        None,
        (),
        (),
        None,
    )


def _agenda() -> AgendaEntryView:
    return AgendaEntryView(
        uuid4(),
        "EVENT",
        "Project review",
        NOW + timedelta(days=1),
        NOW + timedelta(days=1, hours=1),
        "UTC",
        "ACTIVE",
        ("calendar:existing",),
        uuid4(),
        1,
    )


@pytest.mark.asyncio
async def test_calendar_upsert_uses_private_stable_keys_and_requires_confirmation() -> None:
    repository = Repository()
    agenda = Agenda()
    service = CalendarChangeIngestionService(
        repository,
        HmacCalendarEventFingerprinter(SecretStr("unit-test-calendar-fingerprint-key")),
        agenda,
    )
    values = await service.ingest(
        uuid4(),
        uuid4(),
        "qq-mail:opaque-parent",
        CalendarParseResult("REQUEST", (_event(CalendarChangeKind.UPSERT),)),
        NOW,
    )
    candidate = values[0]
    assert candidate.state is CalendarCandidateState.PENDING_CREATE
    assert len(candidate.external_event_key) == len(candidate.version_key) == 64
    assert "provider-event-uid" not in repr(candidate)
    assert agenda.source_refs == [f"calendar:{candidate.external_event_key}"]


@pytest.mark.asyncio
async def test_calendar_cancellation_matches_agenda_without_mutating_it() -> None:
    repository = Repository()
    matched = _agenda()
    service = CalendarChangeIngestionService(
        repository,
        HmacCalendarEventFingerprinter(SecretStr("unit-test-calendar-fingerprint-key")),
        Agenda(matched),
    )
    values = await service.ingest(
        uuid4(),
        uuid4(),
        None,
        CalendarParseResult("CANCEL", (_event(CalendarChangeKind.CANCEL, 2),)),
        NOW,
    )
    assert values[0].state is CalendarCandidateState.PENDING_CANCEL
    assert values[0].agenda_entry_id == matched.agenda_entry_id
