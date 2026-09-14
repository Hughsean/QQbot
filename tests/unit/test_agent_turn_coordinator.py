import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.modules.agent.application import ConversationTurnCoordinator
from qq_time_agent.modules.agent.contracts import (
    AgentTurnClaim,
    AgentTurnSegmentRef,
    AgentTurnTicket,
    TurnClaimDecision,
    TurnClaimResult,
)


@dataclass
class MemoryTurnRepository:
    turn_id: UUID = field(default_factory=uuid4)
    generation: int = 0
    ready_at: datetime | None = None
    status: str = "OPEN"
    key_hash: str = ""
    segments: list[AgentTurnSegmentRef] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def stage(self, **values: object) -> AgentTurnTicket:
        async with self.lock:
            self.generation += 1
            now = values["now"]
            assert isinstance(now, datetime)
            quiet = values["quiet_seconds"]
            assert isinstance(quiet, float)
            self.ready_at = datetime.fromtimestamp(now.timestamp() + quiet, UTC)
            self.key_hash = str(values["conversation_key_hash"])
            self.segments.append(
                AgentTurnSegmentRef(
                    values["inbox_item_id"],  # type: ignore[arg-type]
                    self.generation,
                    str(values["source_type"]),
                    str(values["trust_level"]),
                    values["occurred_at"],  # type: ignore[arg-type]
                    values["provider_sequence"],  # type: ignore[arg-type]
                    values["reference_hash"],  # type: ignore[arg-type]
                    values["content_chars"],  # type: ignore[arg-type]
                )
            )
            return AgentTurnTicket(self.turn_id, self.generation, self.ready_at)

    async def try_claim(
        self,
        ticket: AgentTurnTicket,
        lease_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> TurnClaimResult:
        del lease_until
        async with self.lock:
            if ticket.generation != self.generation:
                return TurnClaimResult(TurnClaimDecision.SUPERSEDED)
            assert self.ready_at is not None
            if now < self.ready_at:
                return TurnClaimResult(TurnClaimDecision.WAIT, retry_at=self.ready_at)
            self.status = "LEASED"
            return TurnClaimResult(
                TurnClaimDecision.CLAIMED,
                AgentTurnClaim(
                    self.turn_id,
                    self.generation,
                    self.key_hash,
                    lease_owner,
                    tuple(self.segments),
                ),
            )

    async def complete(self, claim: AgentTurnClaim, now: datetime) -> None:
        del claim, now
        self.status = "COMPLETED"

    async def release(self, claim: AgentTurnClaim, now: datetime) -> None:
        del claim, now
        self.status = "OPEN"

    async def fail(self, claim: AgentTurnClaim, failure_class: str, now: datetime) -> None:
        del claim, failure_class, now
        self.status = "FAILED"


@pytest.mark.asyncio
async def test_latest_callback_owns_one_coalesced_turn() -> None:
    repository = MemoryTurnRepository()
    coordinator = ConversationTurnCoordinator(
        repository,
        SystemClock(),
        quiet_seconds=0.05,
        max_batch_seconds=0.2,
    )
    occurred_at = datetime.now(UTC)

    async def accept(sequence: int):
        ticket = await coordinator.stage(
            user_id="owner",
            conversation_key="owner",
            inbox_item_id=uuid4(),
            source_type="QQ_DIRECT",
            trust_level="T1",
            occurred_at=occurred_at,
            provider_sequence=sequence,
            reference_hash=None,
            content_chars=10,
        )
        return await coordinator.settle(ticket)

    first = asyncio.create_task(accept(1))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(accept(2))
    first_claim, second_claim = await asyncio.gather(first, second)

    assert first_claim is None
    assert second_claim is not None
    assert [item.provider_sequence for item in second_claim.segments] == [1, 2]
