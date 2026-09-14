"""PostgreSQL persistence for durable, per-conversation turn coordination."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agent.contracts import (
    AgentTurnClaim,
    AgentTurnSegmentRef,
    AgentTurnTicket,
    TurnClaimDecision,
    TurnClaimResult,
)
from qq_time_agent.modules.agent.infrastructure.tables import (
    AgentTurnBatchRow,
    AgentTurnSegmentRow,
)

_OPEN = "OPEN"
_LEASED = "LEASED"
_COMPLETED = "COMPLETED"
_FAILED = "FAILED"


class SqlAgentTurnRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

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
    ) -> AgentTurnTicket:
        _validate_stage(conversation_key_hash, content_chars, now, occurred_at)
        async with self._sessions.begin() as session:
            await _lock_conversation(session, conversation_key_hash)
            duplicate = await session.scalar(
                select(AgentTurnSegmentRow).where(
                    AgentTurnSegmentRow.inbox_item_id == inbox_item_id
                )
            )
            if duplicate is not None:
                duplicate_batch = await _required_batch(session, duplicate.turn_id)
                return _ticket(duplicate_batch)
            open_batch = await session.scalar(
                select(AgentTurnBatchRow)
                .where(
                    AgentTurnBatchRow.conversation_key_hash == conversation_key_hash,
                    AgentTurnBatchRow.status == _OPEN,
                )
                .order_by(AgentTurnBatchRow.created_at.desc(), AgentTurnBatchRow.turn_id)
                .limit(1)
                .with_for_update()
            )
            if open_batch is None or not _can_join(
                open_batch, now, content_chars, max_messages, max_chars
            ):
                batch = _new_batch(
                    user_id,
                    conversation_key_hash,
                    content_chars,
                    now,
                    quiet_seconds,
                    max_batch_seconds,
                )
                session.add(batch)
                await session.flush()
            else:
                batch = open_batch
                batch.generation += 1
                batch.message_count += 1
                batch.content_chars += content_chars
                batch.ready_at = min(now + timedelta(seconds=quiet_seconds), batch.hard_deadline_at)
                batch.updated_at = now
            session.add(
                AgentTurnSegmentRow(
                    turn_id=batch.turn_id,
                    position=batch.message_count,
                    inbox_item_id=inbox_item_id,
                    source_type=source_type,
                    trust_level=trust_level,
                    occurred_at=occurred_at,
                    provider_sequence=provider_sequence,
                    reference_hash=reference_hash,
                    content_chars=content_chars,
                    created_at=now,
                )
            )
            await session.flush()
            return _ticket(batch)

    async def try_claim(
        self,
        ticket: AgentTurnTicket,
        lease_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> TurnClaimResult:
        if not lease_owner.strip() or lease_until <= now:
            raise ValueError("Turn claim requires a future lease")
        async with self._sessions.begin() as session:
            batch = await session.get(AgentTurnBatchRow, ticket.turn_id, with_for_update=True)
            if batch is None:
                return TurnClaimResult(TurnClaimDecision.SUPERSEDED)
            await _lock_conversation(session, batch.conversation_key_hash)
            if batch.generation != ticket.generation or batch.status in {_COMPLETED, _FAILED}:
                return TurnClaimResult(TurnClaimDecision.SUPERSEDED)
            if batch.status == _LEASED:
                if batch.lease_owner == lease_owner:
                    return TurnClaimResult(
                        TurnClaimDecision.CLAIMED,
                        await _claim_view(session, batch),
                    )
                if batch.lease_until is not None and batch.lease_until > now:
                    return TurnClaimResult(
                        TurnClaimDecision.WAIT,
                        retry_at=min(batch.lease_until, now + timedelta(milliseconds=200)),
                    )
                batch.status = _OPEN
                batch.lease_owner = None
                batch.lease_until = None
                batch.failure_class = "TurnLeaseRecovered"
            if now < batch.ready_at:
                return TurnClaimResult(TurnClaimDecision.WAIT, retry_at=batch.ready_at)
            blocker = await _older_blocker(session, batch)
            if blocker is not None:
                expired_lease = (
                    blocker.status == _LEASED
                    and blocker.lease_until is not None
                    and blocker.lease_until <= now
                )
                orphaned_open = (
                    blocker.status == _OPEN
                    and blocker.hard_deadline_at + timedelta(seconds=30) <= now
                )
                if expired_lease or orphaned_open:
                    blocker.status = _FAILED
                    blocker.failure_class = (
                        "TurnLeaseExpired" if expired_lease else "TurnRecoveryMissing"
                    )
                    blocker.updated_at = now
                else:
                    return TurnClaimResult(
                        TurnClaimDecision.WAIT, retry_at=now + timedelta(milliseconds=100)
                    )
            batch.status = _LEASED
            batch.lease_owner = lease_owner
            batch.lease_until = lease_until
            batch.updated_at = now
            await session.flush()
            return TurnClaimResult(
                TurnClaimDecision.CLAIMED,
                await _claim_view(session, batch),
            )

    async def complete(self, claim: AgentTurnClaim, now: datetime) -> None:
        await self._finish(claim, _COMPLETED, None, now)

    async def release(self, claim: AgentTurnClaim, now: datetime) -> None:
        async with self._sessions.begin() as session:
            batch = await session.get(AgentTurnBatchRow, claim.turn_id, with_for_update=True)
            if batch is None:
                raise LookupError("Agent turn does not exist")
            if batch.status != _LEASED or batch.lease_owner != claim.lease_owner:
                raise RuntimeError("Agent turn lease is no longer owned")
            batch.status = _OPEN
            batch.ready_at = now
            batch.lease_owner = None
            batch.lease_until = None
            batch.updated_at = now

    async def fail(self, claim: AgentTurnClaim, failure_class: str, now: datetime) -> None:
        await self._finish(claim, _FAILED, failure_class, now)

    async def _finish(
        self,
        claim: AgentTurnClaim,
        status: str,
        failure_class: str | None,
        now: datetime,
    ) -> None:
        async with self._sessions.begin() as session:
            batch = await session.get(AgentTurnBatchRow, claim.turn_id, with_for_update=True)
            if batch is None:
                raise LookupError("Agent turn does not exist")
            if batch.status == status:
                return
            if batch.status != _LEASED or batch.lease_owner != claim.lease_owner:
                raise RuntimeError("Agent turn lease is no longer owned")
            batch.status = status
            batch.failure_class = failure_class
            batch.lease_owner = None
            batch.lease_until = None
            batch.updated_at = now


async def _lock_conversation(session: AsyncSession, key_hash: str) -> None:
    await session.scalar(select(func.pg_advisory_xact_lock(func.hashtextextended(key_hash, 0))))


async def _required_batch(session: AsyncSession, turn_id: UUID) -> AgentTurnBatchRow:
    batch = await session.get(AgentTurnBatchRow, turn_id)
    if batch is None:
        raise RuntimeError("Agent turn segment lost its batch")
    return batch


async def _older_blocker(
    session: AsyncSession, batch: AgentTurnBatchRow
) -> AgentTurnBatchRow | None:
    result = await session.scalars(
        select(AgentTurnBatchRow)
        .where(
            AgentTurnBatchRow.conversation_key_hash == batch.conversation_key_hash,
            AgentTurnBatchRow.status.in_((_OPEN, _LEASED)),
            AgentTurnBatchRow.created_at < batch.created_at,
        )
        .order_by(AgentTurnBatchRow.created_at, AgentTurnBatchRow.turn_id)
        .limit(1)
        .with_for_update()
    )
    return result.first()


async def _claim_view(session: AsyncSession, batch: AgentTurnBatchRow) -> AgentTurnClaim:
    rows = list(
        await session.scalars(
            select(AgentTurnSegmentRow)
            .where(AgentTurnSegmentRow.turn_id == batch.turn_id)
            .order_by(
                AgentTurnSegmentRow.provider_sequence.asc().nulls_last(),
                AgentTurnSegmentRow.occurred_at,
                AgentTurnSegmentRow.position,
            )
        )
    )
    if not rows or batch.lease_owner is None:
        raise RuntimeError("Claimed Agent turn has no segments or lease owner")
    return AgentTurnClaim(
        batch.turn_id,
        batch.generation,
        batch.conversation_key_hash,
        batch.lease_owner,
        tuple(
            AgentTurnSegmentRef(
                row.inbox_item_id,
                row.position,
                row.source_type,
                row.trust_level,
                row.occurred_at,
                row.provider_sequence,
                row.reference_hash,
                row.content_chars,
            )
            for row in rows
        ),
    )


def _new_batch(
    user_id: str,
    key_hash: str,
    content_chars: int,
    now: datetime,
    quiet_seconds: float,
    max_batch_seconds: float,
) -> AgentTurnBatchRow:
    return AgentTurnBatchRow(
        turn_id=uuid4(),
        user_id=user_id,
        conversation_key_hash=key_hash,
        status=_OPEN,
        generation=1,
        message_count=1,
        content_chars=content_chars,
        ready_at=now + timedelta(seconds=quiet_seconds),
        hard_deadline_at=now + timedelta(seconds=max_batch_seconds),
        lease_owner=None,
        lease_until=None,
        failure_class=None,
        created_at=now,
        updated_at=now,
    )


def _can_join(
    batch: AgentTurnBatchRow,
    now: datetime,
    content_chars: int,
    max_messages: int,
    max_chars: int,
) -> bool:
    return (
        now < batch.hard_deadline_at
        and batch.message_count < max_messages
        and batch.content_chars + content_chars <= max_chars
    )


def _ticket(batch: AgentTurnBatchRow) -> AgentTurnTicket:
    return AgentTurnTicket(batch.turn_id, batch.generation, batch.ready_at)


def _validate_stage(
    key_hash: str, content_chars: int, now: datetime, occurred_at: datetime
) -> None:
    if len(key_hash) != 64 or content_chars < 0:
        raise ValueError("Turn stage metadata is invalid")
    for value in (now, occurred_at):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Turn stage times must be timezone-aware")
