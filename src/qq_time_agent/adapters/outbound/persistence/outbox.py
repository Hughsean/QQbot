"""Transactional Outbox persistence operations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.operations_tables import OutboxEventRow
from qq_time_agent.contracts.events import EventEnvelope


class SqlOutbox:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def append(session: AsyncSession, event: EventEnvelope) -> None:
        _validate_event(event)
        session.add(
            OutboxEventRow(
                event_id=event.event_id,
                event_type=event.event_type,
                schema_version=event.schema_version,
                aggregate_ref=event.aggregate_ref,
                payload=event.payload,
                occurred_at=event.occurred_at,
            )
        )

    async def unpublished(self, limit: int = 100) -> list[EventEnvelope]:
        async with self._sessions() as session:
            rows = list(
                await session.scalars(
                    select(OutboxEventRow)
                    .where(OutboxEventRow.published_at.is_(None))
                    .order_by(OutboxEventRow.occurred_at, OutboxEventRow.event_id)
                    .limit(limit)
                )
            )
            return [_to_envelope(row) for row in rows]

    async def mark_published(self, event_id: UUID, published_at: datetime) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(OutboxEventRow)
                .where(
                    OutboxEventRow.event_id == event_id,
                    OutboxEventRow.published_at.is_(None),
                )
                .values(published_at=published_at)
            )


def _to_envelope(row: OutboxEventRow) -> EventEnvelope:
    return EventEnvelope(
        row.event_id,
        row.event_type,
        row.schema_version,
        row.aggregate_ref,
        row.payload,
        row.occurred_at,
    )


def _validate_event(event: EventEnvelope) -> None:
    if not event.event_type.strip() or event.schema_version < 1:
        raise ValueError("event type and positive schema version required")
    if event.occurred_at.tzinfo is None or event.occurred_at.utcoffset() is None:
        raise ValueError("event occurred_at must be timezone-aware")
