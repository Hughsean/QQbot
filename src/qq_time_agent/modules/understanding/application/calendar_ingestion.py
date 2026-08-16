"""Map deterministic calendar output into persistent confirmation candidates."""

from datetime import datetime
from uuid import UUID

from qq_time_agent.modules.agenda.contracts import AgendaSourceLookupPort
from qq_time_agent.modules.normalization.contracts import (
    CalendarChangeKind as NormalizedChangeKind,
)
from qq_time_agent.modules.normalization.contracts import CalendarParseResult
from qq_time_agent.modules.understanding.application.ports import (
    CalendarChangeRepository,
    CalendarEventFingerprinter,
)
from qq_time_agent.modules.understanding.domain.calendar_changes import (
    CalendarCandidateState,
    CalendarChangeCandidate,
    CalendarChangeKind,
)


class CalendarChangeIngestionService:
    def __init__(
        self,
        repository: CalendarChangeRepository,
        fingerprinter: CalendarEventFingerprinter,
        agenda: AgendaSourceLookupPort,
    ) -> None:
        self._repository = repository
        self._fingerprinter = fingerprinter
        self._agenda = agenda

    async def ingest(
        self,
        asset_id: UUID,
        inbox_item_id: UUID,
        parent_source_ref: str | None,
        calendar: CalendarParseResult,
        now: datetime,
    ) -> tuple[CalendarChangeCandidate, ...]:
        results: list[CalendarChangeCandidate] = []
        for event in calendar.events:
            recurrence_id = (
                event.recurrence_id.isoformat() if event.recurrence_id is not None else None
            )
            event_key = self._fingerprinter.event_key(event.uid, recurrence_id)
            source_ref = f"calendar:{event_key}"
            agenda_entry = await self._agenda.find_by_source_ref(source_ref)
            state = _candidate_state(event.change_kind, agenda_entry is not None)
            candidate = CalendarChangeCandidate.create(
                asset_id,
                inbox_item_id,
                event_key,
                self._fingerprinter.version_key(event_key, event.sequence),
                event.sequence,
                CalendarChangeKind(event.change_kind.value),
                event.title,
                event.starts_at,
                event.ends_at,
                event.timezone,
                event.location,
                event.participants,
                event.recurrence_rule,
                state,
                None if agenda_entry is None else agenda_entry.agenda_entry_id,
                parent_source_ref,
                now,
            )
            results.append(await self._repository.add_version(candidate))
        return tuple(results)


def _candidate_state(change_kind: NormalizedChangeKind, matched: bool) -> CalendarCandidateState:
    if change_kind is NormalizedChangeKind.CANCEL:
        return (
            CalendarCandidateState.PENDING_CANCEL
            if matched
            else CalendarCandidateState.UNMATCHED_CANCEL
        )
    return (
        CalendarCandidateState.PENDING_UPDATE if matched else CalendarCandidateState.PENDING_CREATE
    )
