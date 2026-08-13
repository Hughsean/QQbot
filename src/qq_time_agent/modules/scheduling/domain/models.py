"""Versioned proposal aggregate and validated time slots."""

import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qq_time_agent.modules.scheduling.contracts import ProposalConflict, ProposalSlot


class ProposalStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(slots=True)
class SchedulingProposal:
    proposal_id: UUID
    user_id: str
    candidate_id: UUID
    candidate_kind: str
    title: str
    recommended_slot: ProposalSlot | None
    alternative_slots: tuple[ProposalSlot, ...]
    conflicts: tuple[ProposalConflict, ...]
    rationale: str
    assumptions: tuple[str, ...]
    source_refs: tuple[str, ...]
    expires_at: datetime
    constraint_snapshot: dict[str, object]
    status: ProposalStatus = ProposalStatus.PENDING_CONFIRMATION
    version: int = 1

    @classmethod
    def create(
        cls,
        user_id: str,
        candidate_id: UUID,
        candidate_kind: str,
        title: str,
        recommended_slot: ProposalSlot | None,
        alternative_slots: tuple[ProposalSlot, ...],
        conflicts: tuple[ProposalConflict, ...],
        rationale: str,
        assumptions: tuple[str, ...],
        source_refs: tuple[str, ...],
        expires_at: datetime,
        constraint_snapshot: dict[str, object],
    ) -> "SchedulingProposal":
        value = cls(
            uuid4(),
            user_id,
            candidate_id,
            candidate_kind,
            title,
            recommended_slot,
            alternative_slots,
            conflicts,
            rationale,
            assumptions,
            source_refs,
            expires_at,
            constraint_snapshot,
        )
        value.validate()
        return value

    def validate(self) -> None:
        if self.candidate_kind not in {"EVENT", "TASK"}:
            raise ValueError("Proposal candidate kind is invalid")
        if (
            not self.user_id.strip()
            or not self.title.strip()
            or not self.source_refs
            or not self.rationale.strip()
        ):
            raise ValueError("Proposal owner, title, source references, and rationale are required")
        if len(self.alternative_slots) > 2:
            raise ValueError("Proposal may contain at most two alternatives")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("Proposal expiry must be timezone-aware")
        for slot in _slots(self):
            _validate_slot(slot)

    def confirm(self, user_id: str, version: int, token: str, now: datetime) -> None:
        self._require_pending(user_id, version, now)
        expected = f"{self.proposal_id.hex[:8]}-{self.version}"
        if not secrets.compare_digest(token.casefold(), expected.casefold()):
            raise ValueError("confirmation token is invalid")
        self.status = ProposalStatus.CONFIRMED
        self.version += 1

    def revise(
        self, user_id: str, version: int, selected_slot: ProposalSlot, now: datetime
    ) -> None:
        self._require_pending(user_id, version, now)
        _validate_slot(selected_slot)
        available = _slots(self)
        if selected_slot not in available:
            raise ValueError("revision slot is not part of this Proposal")
        self.recommended_slot = selected_slot
        self.alternative_slots = tuple(slot for slot in available if slot != selected_slot)[:2]
        self.version += 1

    def reject(self, user_id: str, version: int, now: datetime) -> None:
        self._require_pending(user_id, version, now)
        self.status = ProposalStatus.REJECTED
        self.version += 1

    def mark_executed(self, version: int) -> None:
        if self.status is not ProposalStatus.CONFIRMED or self.version != version:
            raise ValueError("only the current confirmed Proposal can be executed")
        self.status = ProposalStatus.EXECUTED
        self.version += 1

    def _require_pending(self, user_id: str, version: int, now: datetime) -> None:
        if self.user_id != user_id:
            raise PermissionError("Proposal belongs to another user")
        if self.version != version:
            raise ValueError("Proposal version is stale")
        if self.status is not ProposalStatus.PENDING_CONFIRMATION:
            raise ValueError("Proposal is not pending confirmation")
        if now >= self.expires_at:
            self.status = ProposalStatus.EXPIRED
            self.version += 1
            raise ValueError("Proposal has expired")


def _slots(value: SchedulingProposal) -> tuple[ProposalSlot, ...]:
    prefix = () if value.recommended_slot is None else (value.recommended_slot,)
    return prefix + value.alternative_slots


def _validate_slot(value: ProposalSlot) -> None:
    try:
        ZoneInfo(value.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Proposal slot timezone is invalid") from exc
    if value.starts_at.tzinfo is None or value.ends_at.tzinfo is None:
        raise ValueError("Proposal slot must be timezone-aware")
    if value.ends_at <= value.starts_at:
        raise ValueError("Proposal slot end must follow start")
