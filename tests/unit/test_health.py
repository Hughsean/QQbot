from dataclasses import dataclass

from fastapi.testclient import TestClient

from qq_time_agent.adapters.inbound.http.app import create_app
from qq_time_agent.adapters.inbound.http.health import ReadinessService
from qq_time_agent.modules.embeddings.contracts import (
    EmbeddingBatch,
    EmbeddingProviderHealth,
)


@dataclass(frozen=True)
class DatabaseStatus:
    available: bool
    vector_enabled: bool


class DatabaseProbe:
    def __init__(self, available: bool) -> None:
        self._available = available

    async def check(self) -> DatabaseStatus:
        return DatabaseStatus(self._available, self._available)


class Embeddings:
    def __init__(self, available: bool) -> None:
        self._available = available

    async def embed(self, texts: tuple[str, ...], model_id: str, dimensions: int) -> EmbeddingBatch:
        return EmbeddingBatch(model_id, "digest", dimensions, ())

    async def health(self) -> EmbeddingProviderHealth:
        return EmbeddingProviderHealth(self._available, "model", 1024, "digest")


def test_live_does_not_depend_on_external_services() -> None:
    client = TestClient(create_app(ReadinessService(DatabaseProbe(False), Embeddings(False))))
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "dependencies": None}


def test_ready_reports_only_dependency_classes() -> None:
    client = TestClient(create_app(ReadinessService(DatabaseProbe(True), Embeddings(False))))
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"database": True, "embeddings": False},
    }
