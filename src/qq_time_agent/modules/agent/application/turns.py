"""Durable quiet-window coordination for ordered conversation turns."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agent.contracts import (
    AgentTurnClaim,
    AgentTurnRepository,
    AgentTurnTicket,
    TurnClaimDecision,
)

Sleep = Callable[[float], Awaitable[None]]


class ConversationTurnCoordinator:
    def __init__(
        self,
        repository: AgentTurnRepository,
        clock: Clock,
        *,
        quiet_seconds: float = 1.2,
        max_batch_seconds: float = 4.0,
        max_messages: int = 8,
        max_chars: int = 12_000,
        lease_seconds: float = 300.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        positive = (quiet_seconds, max_batch_seconds, lease_seconds)
        if any(value <= 0 for value in positive):
            raise ValueError("Turn timing limits must be positive")
        if quiet_seconds > max_batch_seconds:
            raise ValueError("Turn quiet window exceeds batch deadline")
        if not 1 <= max_messages <= 32 or not 100 <= max_chars <= 100_000:
            raise ValueError("Turn size limits are invalid")
        self._repository = repository
        self._clock = clock
        self._quiet_seconds = quiet_seconds
        self._max_batch_seconds = max_batch_seconds
        self._max_messages = max_messages
        self._max_chars = max_chars
        self._lease_seconds = lease_seconds
        self._sleep = sleep

    async def stage(
        self,
        *,
        user_id: str,
        conversation_key: str,
        inbox_item_id: UUID,
        source_type: str,
        trust_level: str,
        occurred_at: datetime,
        provider_sequence: int | None,
        reference_hash: str | None,
        content_chars: int,
    ) -> AgentTurnTicket:
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("Turn occurrence time must be timezone-aware")
        key_hash = hashlib.sha256(conversation_key.encode()).hexdigest()
        return await self._repository.stage(
            user_id=user_id,
            conversation_key_hash=key_hash,
            inbox_item_id=inbox_item_id,
            source_type=source_type,
            trust_level=trust_level,
            occurred_at=occurred_at,
            provider_sequence=provider_sequence,
            reference_hash=reference_hash,
            content_chars=content_chars,
            now=self._clock.now(),
            quiet_seconds=self._quiet_seconds,
            max_batch_seconds=self._max_batch_seconds,
            max_messages=self._max_messages,
            max_chars=self._max_chars,
        )

    async def settle(self, ticket: AgentTurnTicket) -> AgentTurnClaim | None:
        lease_owner = f"qq-turn:{uuid4().hex}"
        while True:
            now = self._clock.now()
            result = await self._repository.try_claim(
                ticket,
                lease_owner,
                now,
                now + timedelta(seconds=self._lease_seconds),
            )
            if result.decision is TurnClaimDecision.CLAIMED:
                return result.claim
            if result.decision is TurnClaimDecision.SUPERSEDED:
                return None
            delay = 0.1
            if result.retry_at is not None:
                delay = max(0.01, min(0.2, (result.retry_at - now).total_seconds()))
            await self._sleep(delay)

    async def complete(self, claim: AgentTurnClaim) -> None:
        await self._repository.complete(claim, self._clock.now())

    async def release(self, claim: AgentTurnClaim) -> None:
        await self._repository.release(claim, self._clock.now())

    async def fail(self, claim: AgentTurnClaim, failure_class: str) -> None:
        await self._repository.fail(claim, failure_class[:120], self._clock.now())
