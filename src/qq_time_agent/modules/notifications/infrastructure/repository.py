"""PostgreSQL idempotent Notification delivery repository."""

from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.notifications.application.ports import StoredDelivery
from qq_time_agent.modules.notifications.contracts import NotificationIntentMetrics
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntent,
    NotificationIntentDraft,
    NotificationIntentState,
    NotificationKind,
)
from qq_time_agent.modules.notifications.infrastructure.tables import (
    DeliveryRow,
    NotificationIntentRow,
)


class SqlDeliveryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, idempotency_key: str) -> StoredDelivery | None:
        async with self._sessions() as session:
            row = await session.get(DeliveryRow, idempotency_key)
            return None if row is None else _to_delivery(row)

    async def record(self, value: StoredDelivery) -> StoredDelivery:
        async with self._sessions.begin() as session:
            await session.execute(
                insert(DeliveryRow)
                .values(
                    idempotency_key=value.idempotency_key,
                    delivery_id=value.delivery_id,
                    sent_at=value.sent_at,
                )
                .on_conflict_do_nothing(index_elements=[DeliveryRow.idempotency_key])
            )
            row = await session.scalar(
                select(DeliveryRow).where(DeliveryRow.idempotency_key == value.idempotency_key)
            )
            if row is None:
                raise RuntimeError("idempotent Notification record lost stored row")
            return _to_delivery(row)


_BLOCKING_STATES = (
    NotificationIntentState.PENDING.value,
    NotificationIntentState.LEASED.value,
    NotificationIntentState.AMBIGUOUS.value,
    NotificationIntentState.DEAD_LETTER.value,
)


class SqlNotificationIntentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add_or_get(self, draft: NotificationIntentDraft, now: datetime) -> NotificationIntent:
        value = NotificationIntent.create(draft, now)
        async with self._sessions.begin() as session:
            await session.execute(
                insert(NotificationIntentRow)
                .values(**_intent_values(value))
                .on_conflict_do_nothing()
            )
            row = await session.scalar(
                select(NotificationIntentRow).where(
                    NotificationIntentRow.idempotency_key == draft.idempotency_key
                )
            )
            if row is None:
                row = await session.scalar(
                    select(NotificationIntentRow).where(
                        NotificationIntentRow.subject_key == draft.subject_key,
                        NotificationIntentRow.state.in_(_BLOCKING_STATES),
                    )
                )
            if row is None:
                raise RuntimeError("idempotent notification intent insert lost row")
            return _to_intent(row)

    async def lease_due(
        self, now: datetime, owner: str, duration: timedelta, limit: int
    ) -> tuple[NotificationIntent, ...]:
        if limit < 1 or duration <= timedelta(0):
            raise ValueError("notification lease limits must be positive")
        async with self._sessions.begin() as session:
            rows = tuple(
                await session.scalars(
                    select(NotificationIntentRow)
                    .where(
                        NotificationIntentRow.state == NotificationIntentState.PENDING.value,
                        NotificationIntentRow.available_at <= now,
                    )
                    .order_by(NotificationIntentRow.available_at, NotificationIntentRow.intent_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            values: list[NotificationIntent] = []
            for row in rows:
                value = _to_intent(row)
                value.lease(owner, now + duration, now)
                _assign_intent(row, value)
                values.append(value)
            return tuple(values)

    async def save(self, intent: NotificationIntent, expected_version: int) -> None:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(NotificationIntentRow)
                .where(
                    NotificationIntentRow.intent_id == intent.intent_id,
                    NotificationIntentRow.version == expected_version,
                )
                .values(**_intent_values(intent))
            )
            if cast("CursorResult[tuple[()]]", result).rowcount != 1:
                raise RuntimeError("stale notification intent update")

    async def has_open(self, subject_key: str) -> bool:
        async with self._sessions() as session:
            row = await session.scalar(
                select(NotificationIntentRow.intent_id)
                .where(
                    NotificationIntentRow.subject_key == subject_key,
                    NotificationIntentRow.state.in_(_BLOCKING_STATES),
                )
                .limit(1)
            )
            return row is not None

    async def has_recent_sent(self, subject_key: str, since: datetime) -> bool:
        async with self._sessions() as session:
            row = await session.scalar(
                select(NotificationIntentRow.intent_id)
                .where(
                    NotificationIntentRow.subject_key == subject_key,
                    NotificationIntentRow.state == NotificationIntentState.SENT.value,
                    NotificationIntentRow.sent_at >= since,
                )
                .limit(1)
            )
            return row is not None

    async def notification_metrics(self) -> NotificationIntentMetrics:
        async with self._sessions() as session:
            rows = tuple(
                await session.execute(
                    select(NotificationIntentRow.state, func.count()).group_by(
                        NotificationIntentRow.state
                    )
                )
            )
        counts = {str(state): float(count) for state, count in rows}
        return NotificationIntentMetrics(
            counts.get(NotificationIntentState.PENDING.value, 0.0),
            counts.get(NotificationIntentState.LEASED.value, 0.0),
            counts.get(NotificationIntentState.AMBIGUOUS.value, 0.0),
            counts.get(NotificationIntentState.DEAD_LETTER.value, 0.0),
        )

    async def recover_expired(self, now: datetime, limit: int) -> int:
        if limit < 1:
            raise ValueError("notification recovery limit must be positive")
        async with self._sessions.begin() as session:
            rows = tuple(
                await session.scalars(
                    select(NotificationIntentRow)
                    .where(
                        NotificationIntentRow.state == NotificationIntentState.LEASED.value,
                        NotificationIntentRow.lease_until < now,
                    )
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                value = _to_intent(row)
                value.mark_ambiguous("LeaseExpiredAmbiguous", now)
                _assign_intent(row, value)
            return len(rows)


def _to_delivery(row: DeliveryRow) -> StoredDelivery:
    return StoredDelivery(row.idempotency_key, row.delivery_id, row.sent_at)


def _intent_values(value: NotificationIntent) -> dict[str, object]:
    return {
        "intent_id": value.intent_id,
        "user_id": value.draft.user_id,
        "kind": value.draft.kind.value,
        "subject_key": value.draft.subject_key,
        "idempotency_key": value.draft.idempotency_key,
        "template_version": value.draft.template_version,
        "content": value.draft.content,
        "state": value.state.value,
        "available_at": value.draft.available_at,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
        "attempt_count": value.attempt_count,
        "lease_owner": value.lease_owner,
        "lease_until": value.lease_until,
        "provider_delivery_id": value.provider_delivery_id,
        "failure_class": value.failure_class,
        "sent_at": value.sent_at,
        "version": value.version,
    }


def _assign_intent(row: NotificationIntentRow, value: NotificationIntent) -> None:
    for key, item in _intent_values(value).items():
        setattr(row, key, item)


def _to_intent(row: NotificationIntentRow) -> NotificationIntent:
    return NotificationIntent(
        row.intent_id,
        NotificationIntentDraft(
            row.user_id,
            NotificationKind(row.kind),
            row.subject_key,
            row.idempotency_key,
            row.template_version,
            row.content,
            row.available_at,
        ),
        NotificationIntentState(row.state),
        row.created_at,
        row.updated_at,
        row.attempt_count,
        row.lease_owner,
        row.lease_until,
        row.provider_delivery_id,
        row.failure_class,
        row.sent_at,
        row.version,
    )
