"""Serialized idempotent persistence for external calendar event versions."""

from dataclasses import replace

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.understanding.domain.calendar_changes import (
    CalendarCandidateState,
    CalendarChangeCandidate,
    CalendarChangeKind,
)
from qq_time_agent.modules.understanding.infrastructure.tables import CalendarChangeCandidateRow

_PENDING_STATES = {
    CalendarCandidateState.PENDING_CREATE.value,
    CalendarCandidateState.PENDING_UPDATE.value,
    CalendarCandidateState.PENDING_CANCEL.value,
    CalendarCandidateState.UNMATCHED_CANCEL.value,
}


class SqlCalendarChangeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add_version(self, candidate: CalendarChangeCandidate) -> CalendarChangeCandidate:
        async with self._sessions.begin() as session:
            await session.execute(
                select(func.pg_advisory_xact_lock(_lock_key(candidate.external_event_key)))
            )
            existing = await session.scalar(
                select(CalendarChangeCandidateRow).where(
                    CalendarChangeCandidateRow.version_key == candidate.version_key
                )
            )
            if existing is not None:
                return _to_domain(existing)
            latest = await session.scalar(
                select(CalendarChangeCandidateRow)
                .where(
                    CalendarChangeCandidateRow.external_event_key == candidate.external_event_key
                )
                .order_by(CalendarChangeCandidateRow.sequence.desc())
                .limit(1)
            )
            if latest is not None and latest.sequence >= candidate.sequence:
                candidate = replace(candidate, state=CalendarCandidateState.STALE)
            else:
                await session.execute(
                    update(CalendarChangeCandidateRow)
                    .where(
                        CalendarChangeCandidateRow.external_event_key
                        == candidate.external_event_key,
                        CalendarChangeCandidateRow.state.in_(_PENDING_STATES),
                    )
                    .values(state=CalendarCandidateState.SUPERSEDED.value)
                )
            await session.execute(insert(CalendarChangeCandidateRow).values(**_values(candidate)))
        return candidate


def _values(value: CalendarChangeCandidate) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,
        "asset_id": value.asset_id,
        "inbox_item_id": value.inbox_item_id,
        "external_event_key": value.external_event_key,
        "version_key": value.version_key,
        "sequence": value.sequence,
        "change_kind": value.change_kind.value,
        "state": value.state.value,
        "title": value.title,
        "starts_at": value.starts_at,
        "ends_at": value.ends_at,
        "timezone": value.timezone,
        "location": value.location,
        "participants": list(value.participants),
        "recurrence_rule": value.recurrence_rule,
        "agenda_entry_id": value.agenda_entry_id,
        "parent_source_ref": value.parent_source_ref,
        "created_at": value.created_at,
    }


def _to_domain(row: CalendarChangeCandidateRow) -> CalendarChangeCandidate:
    return CalendarChangeCandidate(
        row.candidate_id,
        row.asset_id,
        row.inbox_item_id,
        row.external_event_key,
        row.version_key,
        row.sequence,
        CalendarChangeKind(row.change_kind),
        CalendarCandidateState(row.state),
        row.title,
        row.starts_at,
        row.ends_at,
        row.timezone,
        row.location,
        tuple(row.participants),
        row.recurrence_rule,
        row.agenda_entry_id,
        row.parent_source_ref,
        row.created_at,
    )


def _lock_key(value: str) -> int:
    raw = int(value[:16], 16)
    return raw if raw < (1 << 63) else raw - (1 << 64)
