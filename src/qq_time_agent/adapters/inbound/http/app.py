"""HTTP application factory."""

from fastapi import APIRouter, FastAPI
from starlette.types import Lifespan

from qq_time_agent.adapters.inbound.http.health import ReadinessService, health_router


def create_app(
    readiness: ReadinessService,
    lifespan: Lifespan[FastAPI] | None = None,
    routers: tuple[APIRouter, ...] = (),
) -> FastAPI:
    app = FastAPI(
        title="QQ Time Agent",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.include_router(health_router(readiness))
    for router in routers:
        app.include_router(router)
    return app
