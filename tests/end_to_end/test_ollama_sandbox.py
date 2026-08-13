import pytest

from qq_time_agent.adapters.outbound.ollama.embedding import OllamaEmbeddingAdapter
from qq_time_agent.bootstrap.settings import load_runtime_config

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]


async def test_ollama_cold_or_warm_health_and_1024_dimension_contract() -> None:
    adapter = OllamaEmbeddingAdapter(load_runtime_config().ollama, timeout_seconds=90)
    try:
        first = await adapter.health()
        second = await adapter.health()
    finally:
        await adapter.close()
    assert first.available and second.available
    assert first.model_id == "qwen3-embedding:4b"
    assert first.dimensions == second.dimensions == 1024
