"""PostgreSQL idempotent Notification delivery repository."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.notifications.application.ports import StoredDelivery
from qq_time_agent.modules.notifications.infrastructure.tables import DeliveryRow


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


def _to_delivery(row: DeliveryRow) -> StoredDelivery:
    return StoredDelivery(row.idempotency_key, row.delivery_id, row.sent_at)
