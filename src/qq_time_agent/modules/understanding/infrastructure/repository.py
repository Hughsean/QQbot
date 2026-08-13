"""PostgreSQL idempotent candidate repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.understanding.domain.candidates import Candidate
from qq_time_agent.modules.understanding.infrastructure.tables import CandidateRow


class SqlCandidateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, value: Candidate) -> Candidate:
        values = _values(value)
        async with self._sessions.begin() as session:
            await session.execute(
                insert(CandidateRow)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_understanding_candidate_inbox")
            )
            row = await session.scalar(
                select(CandidateRow).where(CandidateRow.inbox_item_id == value.inbox_item_id)
            )
            if row is None:
                raise RuntimeError("idempotent candidate insert lost stored candidate")
            return _to_candidate(row)

    async def get_for_inbox(self, inbox_item_id: UUID) -> Candidate | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(CandidateRow).where(CandidateRow.inbox_item_id == inbox_item_id)
            )
            return None if row is None else _to_candidate(row)

    async def get(self, candidate_id: UUID) -> Candidate | None:
        async with self._sessions() as session:
            row = await session.get(CandidateRow, candidate_id)
            return None if row is None else _to_candidate(row)

    async def list_ids(self, limit: int) -> tuple[UUID, ...]:
        async with self._sessions() as session:
            values = await session.scalars(
                select(CandidateRow.candidate_id).order_by(CandidateRow.candidate_id).limit(limit)
            )
            return tuple(values)


def _values(value: Candidate) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,
        "inbox_item_id": value.inbox_item_id,
        "kind": value.kind.value,
        "title": value.title,
        "starts_at": value.starts_at,
        "ends_at": value.ends_at,
        "deadline": value.deadline,
        "timezone": value.timezone,
        "location": value.location,
        "participants": list(value.participants),
        "estimated_duration_minutes": value.estimated_duration_minutes,
        "priority": value.priority,
        "allowed_windows": list(value.allowed_windows),
        "confidence": value.confidence,
        "assumptions": list(value.assumptions),
        "evidence": list(value.evidence),
        "source_refs": list(value.source_refs),
        "source_ref": value.source_refs[0],
    }


def _to_candidate(row: CandidateRow) -> Candidate:
    from qq_time_agent.modules.understanding.contracts import CandidateKind

    return Candidate(
        row.candidate_id,
        row.inbox_item_id,
        CandidateKind(row.kind),
        row.title,
        row.starts_at,
        row.ends_at,
        row.deadline,
        row.timezone,
        row.location,
        tuple(row.participants),
        row.estimated_duration_minutes,
        row.priority,
        tuple(row.allowed_windows),
        row.confidence,
        tuple(row.assumptions),
        tuple(row.evidence),
        tuple(row.source_refs),
    )
