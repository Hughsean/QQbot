"""Database readiness probe with no connection details in its result."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    available: bool
    vector_enabled: bool


class DatabaseReadinessProbe:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def check(self) -> DatabaseHealth:
        try:
            async with self._engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                result = await connection.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                )
                return DatabaseHealth(True, result.scalar_one_or_none() == 1)
        except Exception:  # readiness deliberately classifies without leaking details
            return DatabaseHealth(False, False)
