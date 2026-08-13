"""Validated Event and Task candidates independent of model providers."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qq_time_agent.modules.understanding.contracts import CandidateKind


@dataclass(frozen=True, slots=True)
class Candidate:
    candidate_id: UUID
    inbox_item_id: UUID
    kind: CandidateKind
    title: str
    starts_at: datetime | None
    ends_at: datetime | None
    deadline: datetime | None
    timezone: str
    location: str | None
    participants: tuple[str, ...]
    estimated_duration_minutes: int | None
    priority: str | None
    allowed_windows: tuple[str, ...]
    confidence: float
    assumptions: tuple[str, ...]
    evidence: tuple[str, ...]
    source_refs: tuple[str, ...]

    @classmethod
    def create(
        cls,
        inbox_item_id: UUID,
        kind: CandidateKind,
        title: str,
        starts_at: datetime | None,
        ends_at: datetime | None,
        deadline: datetime | None,
        timezone: str,
        location: str | None,
        participants: tuple[str, ...],
        estimated_duration_minutes: int | None,
        priority: str | None,
        allowed_windows: tuple[str, ...],
        confidence: float,
        assumptions: tuple[str, ...],
        evidence: tuple[str, ...],
        source_refs: tuple[str, ...],
    ) -> "Candidate":
        value = cls(
            uuid4(),
            inbox_item_id,
            kind,
            title.strip(),
            starts_at,
            ends_at,
            deadline,
            timezone,
            location,
            participants,
            estimated_duration_minutes,
            priority,
            allowed_windows,
            confidence,
            assumptions,
            evidence,
            source_refs,
        )
        value._validate()
        return value

    def _validate(self) -> None:
        if self.kind not in {CandidateKind.EVENT, CandidateKind.TASK}:
            raise ValueError("only Event and Task candidates can be persisted")
        if not self.title or not self.source_refs or not 0 <= self.confidence <= 1:
            raise ValueError("candidate title, source and bounded confidence are required")
        self._validate_time_values()
        self._validate_kind_fields()
        if self.estimated_duration_minutes is not None and self.estimated_duration_minutes < 1:
            raise ValueError("estimated duration must be positive")

    def _validate_time_values(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("candidate timezone is invalid") from exc
        for value in (self.starts_at, self.ends_at, self.deadline):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("candidate times must be timezone-aware")

    def _validate_kind_fields(self) -> None:
        if self.kind is CandidateKind.EVENT:
            if self.starts_at is None or self.ends_at is None or self.ends_at <= self.starts_at:
                raise ValueError("Event requires ordered start and end")
            if self.deadline is not None:
                raise ValueError("Event cannot carry a Task deadline")
        if self.kind is CandidateKind.TASK and (
            self.starts_at is not None or self.ends_at is not None
        ):
            raise ValueError("Task deadline must not be converted to an Event slot")
