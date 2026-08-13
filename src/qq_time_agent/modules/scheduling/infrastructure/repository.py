"""PostgreSQL idempotent Scheduling Proposal repository."""

from collections.abc import Mapping
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.scheduling.contracts import ProposalConflict, ProposalSlot
from qq_time_agent.modules.scheduling.domain.models import (
    ProposalStatus,
    SchedulingProposal,
)
from qq_time_agent.modules.scheduling.infrastructure.tables import ProposalRow


class SqlProposalRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, value: SchedulingProposal) -> SchedulingProposal:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(ProposalRow)
                .values(**_values(value))
                .on_conflict_do_nothing(constraint="uq_scheduling_proposal_candidate")
            )
            row = await session.scalar(
                select(ProposalRow).where(ProposalRow.candidate_id == value.candidate_id)
            )
            if row is None:
                raise RuntimeError("idempotent Proposal insert lost stored proposal")
            return _to_proposal(row)

    async def get(self, proposal_id: UUID) -> SchedulingProposal | None:
        async with self._sessions() as session:
            row = await session.get(ProposalRow, proposal_id)
            return None if row is None else _to_proposal(row)

    async def get_for_candidate(self, candidate_id: UUID) -> SchedulingProposal | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ProposalRow).where(ProposalRow.candidate_id == candidate_id)
            )
            return None if row is None else _to_proposal(row)

    async def save(self, value: SchedulingProposal, expected_version: int) -> None:
        values = _values(value)
        values.pop("proposal_id")
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(ProposalRow)
                .where(
                    ProposalRow.proposal_id == value.proposal_id,
                    ProposalRow.version == expected_version,
                )
                .values(**values)
            )
            if cast("CursorResult[tuple[()]]", result).rowcount != 1:
                raise RuntimeError("Proposal version conflict")

    async def find_confirmable_by_prefix(
        self, proposal_prefix: str, version: int
    ) -> SchedulingProposal | None:
        async with self._sessions() as session:
            rows = tuple(
                await session.scalars(
                    select(ProposalRow).where(
                        ProposalRow.status.in_(
                            (
                                ProposalStatus.PENDING_CONFIRMATION.value,
                                ProposalStatus.CONFIRMED.value,
                            )
                        ),
                    )
                )
            )
            matches = [
                row
                for row in rows
                if row.proposal_id.hex.startswith(proposal_prefix)
                and (
                    (
                        row.status == ProposalStatus.PENDING_CONFIRMATION.value
                        and row.version == version
                    )
                    or (row.status == ProposalStatus.CONFIRMED.value and row.version == version + 1)
                )
            ]
            if len(matches) > 1:
                raise RuntimeError("confirmation token prefix is ambiguous")
            return None if not matches else _to_proposal(matches[0])

    async def list_pending(self, limit: int) -> tuple[SchedulingProposal, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ProposalRow)
                .where(ProposalRow.status == ProposalStatus.PENDING_CONFIRMATION.value)
                .order_by(ProposalRow.expires_at, ProposalRow.proposal_id)
                .limit(limit)
            )
            return tuple(_to_proposal(row) for row in rows)


def _values(value: SchedulingProposal) -> dict[str, object]:
    return {
        "proposal_id": value.proposal_id,
        "user_id": value.user_id,
        "candidate_id": value.candidate_id,
        "candidate_kind": value.candidate_kind,
        "title": value.title,
        "recommended_slot": _slot_value(value.recommended_slot),
        "alternative_slots": [_slot_value(slot) for slot in value.alternative_slots],
        "conflicts": [_conflict_value(conflict) for conflict in value.conflicts],
        "rationale": value.rationale,
        "assumptions": list(value.assumptions),
        "source_refs": list(value.source_refs),
        "source_ref": value.source_refs[0],
        "expires_at": value.expires_at,
        "constraint_snapshot": value.constraint_snapshot,
        "status": value.status.value,
        "version": value.version,
    }


def _slot_value(value: ProposalSlot | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "starts_at": value.starts_at.isoformat(),
        "ends_at": value.ends_at.isoformat(),
        "timezone": value.timezone,
    }


def _conflict_value(value: ProposalConflict) -> dict[str, object]:
    return {
        "agenda_entry_id": str(value.agenda_entry_id),
        "title": value.title,
        "starts_at": value.starts_at.isoformat(),
        "ends_at": value.ends_at.isoformat(),
        "reason": value.reason,
    }


def _to_proposal(row: ProposalRow) -> SchedulingProposal:
    return SchedulingProposal(
        row.proposal_id,
        row.user_id,
        row.candidate_id,
        row.candidate_kind,
        row.title,
        _slot(cast("dict[str, object] | None", row.recommended_slot)),
        tuple(_slot_required(value) for value in row.alternative_slots),
        tuple(_conflict(value) for value in row.conflicts),
        row.rationale,
        tuple(row.assumptions),
        tuple(row.source_refs),
        row.expires_at,
        row.constraint_snapshot,
        ProposalStatus(row.status),
        row.version,
    )


def _slot(value: Mapping[str, object] | None) -> ProposalSlot | None:
    return None if value is None else _slot_required(value)


def _slot_required(value: Mapping[str, object]) -> ProposalSlot:
    return ProposalSlot(
        datetime.fromisoformat(_string(value, "starts_at")),
        datetime.fromisoformat(_string(value, "ends_at")),
        _string(value, "timezone"),
    )


def _conflict(value: Mapping[str, object]) -> ProposalConflict:
    return ProposalConflict(
        UUID(_string(value, "agenda_entry_id")),
        _string(value, "title"),
        datetime.fromisoformat(_string(value, "starts_at")),
        datetime.fromisoformat(_string(value, "ends_at")),
        _string(value, "reason"),
    )


def _string(value: Mapping[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str):
        raise RuntimeError("stored Proposal JSON is invalid")
    return result
