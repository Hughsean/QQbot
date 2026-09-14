"""Provider-neutral contracts for durable, ordered conversation turns."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class TurnClaimDecision(StrEnum):
    CLAIMED = "CLAIMED"
    WAIT = "WAIT"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class AgentTurnTicket:
    turn_id: UUID
    generation: int
    ready_at: datetime


@dataclass(frozen=True, slots=True)
class AgentTurnSegmentRef:
    inbox_item_id: UUID
    position: int
    source_type: str
    trust_level: str
    occurred_at: datetime
    provider_sequence: int | None
    reference_hash: str | None
    content_chars: int


@dataclass(frozen=True, slots=True)
class AgentTurnClaim:
    turn_id: UUID
    generation: int
    conversation_key_hash: str
    lease_owner: str
    segments: tuple[AgentTurnSegmentRef, ...]


@dataclass(frozen=True, slots=True)
class TurnClaimResult:
    decision: TurnClaimDecision
    claim: AgentTurnClaim | None = None
    retry_at: datetime | None = None

    def __post_init__(self) -> None:
        if (self.decision is TurnClaimDecision.CLAIMED) != (self.claim is not None):
            raise ValueError("Turn claim result is inconsistent")


class AgentTurnRepository(Protocol):
    async def stage(
        self,
        *,
        user_id: str,
        conversation_key_hash: str,
        inbox_item_id: UUID,
        source_type: str,
        trust_level: str,
        occurred_at: datetime,
        provider_sequence: int | None,
        reference_hash: str | None,
        content_chars: int,
        now: datetime,
        quiet_seconds: float,
        max_batch_seconds: float,
        max_messages: int,
        max_chars: int,
    ) -> AgentTurnTicket: ...

    async def try_claim(
        self,
        ticket: AgentTurnTicket,
        lease_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> TurnClaimResult: ...

    async def complete(self, claim: AgentTurnClaim, now: datetime) -> None: ...

    async def release(self, claim: AgentTurnClaim, now: datetime) -> None: ...

    async def fail(self, claim: AgentTurnClaim, failure_class: str, now: datetime) -> None: ...
