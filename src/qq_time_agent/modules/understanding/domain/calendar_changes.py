"""Persistent deterministic calendar version and confirmation candidate."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class CalendarChangeKind(StrEnum):
    UPSERT = "UPSERT"
    CANCEL = "CANCEL"


class CalendarCandidateState(StrEnum):
    PENDING_CREATE = "PENDING_CREATE"
    PENDING_UPDATE = "PENDING_UPDATE"
    PENDING_CANCEL = "PENDING_CANCEL"
    UNMATCHED_CANCEL = "UNMATCHED_CANCEL"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class CalendarChangeCandidate:
    candidate_id: UUID
    asset_id: UUID
    inbox_item_id: UUID
    external_event_key: str
    version_key: str
    sequence: int
    change_kind: CalendarChangeKind
    state: CalendarCandidateState
    title: str
    starts_at: datetime | None
    ends_at: datetime | None
    timezone: str
    location: str | None
    participants: tuple[str, ...]
    recurrence_rule: str | None
    agenda_entry_id: UUID | None
    parent_source_ref: str | None
    created_at: datetime

    @classmethod
    def create(
        cls,
        asset_id: UUID,
        inbox_item_id: UUID,
        external_event_key: str,
        version_key: str,
        sequence: int,
        change_kind: CalendarChangeKind,
        title: str,
        starts_at: datetime | None,
        ends_at: datetime | None,
        timezone: str,
        location: str | None,
        participants: tuple[str, ...],
        recurrence_rule: str | None,
        state: CalendarCandidateState,
        agenda_entry_id: UUID | None,
        parent_source_ref: str | None,
        now: datetime,
    ) -> "CalendarChangeCandidate":
        if len(external_event_key) != 64 or len(version_key) != 64:
            raise ValueError("calendar keys must be sha256 values")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("calendar candidate time must be timezone-aware")
        return cls(
            uuid4(),
            asset_id,
            inbox_item_id,
            external_event_key,
            version_key,
            sequence,
            change_kind,
            state,
            title,
            starts_at,
            ends_at,
            timezone,
            location,
            participants,
            recurrence_rule,
            agenda_entry_id,
            parent_source_ref,
            now,
        )
