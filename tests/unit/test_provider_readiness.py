from dataclasses import dataclass

import pytest

from qq_time_agent.adapters.inbound.workers.provider_readiness import EmbeddingStartupGate
from qq_time_agent.modules.embeddings.contracts import EmbeddingBatch, EmbeddingProviderHealth


@dataclass
class FakeEmbeddingProvider:
    health_results: list[EmbeddingProviderHealth]

    async def embed(self, texts: tuple[str, ...], model_id: str, dimensions: int) -> EmbeddingBatch:
        raise AssertionError("startup gate must use health")

    async def health(self) -> EmbeddingProviderHealth:
        return self.health_results.pop(0)


@pytest.mark.asyncio
async def test_startup_gate_waits_until_embedding_provider_is_ready(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeEmbeddingProvider(
        [
            EmbeddingProviderHealth(False, None, None, failure_class="TransientProvider"),
            EmbeddingProviderHealth(False, None, None, failure_class="TransientProvider"),
            EmbeddingProviderHealth(True, "model", 1024, "digest"),
        ]
    )
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with caplog.at_level("INFO"):
        await EmbeddingStartupGate(provider, sleep=sleep, retry_seconds=2).wait()

    assert sleeps == [2, 2]
    assert "waiting for embedding provider" in caplog.text
    assert "embedding provider ready" in caplog.text


def test_startup_gate_rejects_invalid_retry_settings() -> None:
    provider = FakeEmbeddingProvider([])
    with pytest.raises(ValueError, match="positive"):
        EmbeddingStartupGate(provider, retry_seconds=0)
