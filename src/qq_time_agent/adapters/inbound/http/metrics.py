"""Owner-host operational metrics without content or credential labels."""

from dataclasses import dataclass
from typing import Protocol

from fastapi import APIRouter, Response


class MetricsSnapshotPort(Protocol):
    async def snapshot(self) -> dict[str, float]: ...


@dataclass(frozen=True, slots=True)
class MetricsService:
    source: MetricsSnapshotPort

    async def render(self) -> str:
        values = await self.source.snapshot()
        return "".join(f"qq_time_agent_{key} {value}\n" for key, value in sorted(values.items()))


def metrics_router(service: MetricsService) -> APIRouter:
    router = APIRouter()

    @router.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(await service.render(), media_type="text/plain; version=0.0.4")

    return router
