"""FastAPI health endpoints backed by explicit readiness dependencies."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from qq_time_agent.modules.embeddings.contracts import EmbeddingPort


class DatabaseProbe(Protocol):
    async def check(self) -> object: ...


@dataclass(frozen=True, slots=True)
class ReadinessService:
    database: DatabaseProbe
    embeddings: EmbeddingPort

    async def dependencies(self) -> dict[str, bool]:
        database_health, embedding_health = await asyncio.gather(
            self.database.check(), self.embeddings.health()
        )
        database_ready = bool(
            getattr(database_health, "available", False)
            and getattr(database_health, "vector_enabled", False)
        )
        return {
            "database": database_ready,
            "embeddings": embedding_health.available,
        }


class HealthResponse(BaseModel):
    status: str
    dependencies: dict[str, bool] | None = None


def health_router(readiness: ReadinessService) -> APIRouter:
    router = APIRouter()

    @router.get("/health/live", response_model=HealthResponse)
    async def live() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.get("/health/ready", response_model=HealthResponse)
    async def ready(response: Response) -> HealthResponse:
        dependencies = await readiness.dependencies()
        ready_state = all(dependencies.values())
        if not ready_state:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="ready" if ready_state else "not_ready", dependencies=dependencies
        )

    return router
