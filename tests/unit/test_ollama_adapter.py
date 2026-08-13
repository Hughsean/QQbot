import json

import httpx
import pytest

from qq_time_agent.adapters.outbound.ollama.embedding import (
    EmbeddingProviderError,
    OllamaEmbeddingAdapter,
)
from qq_time_agent.bootstrap.config_models import OllamaConfig


def _config() -> OllamaConfig:
    return OllamaConfig("http://127.0.0.1:11434", "qwen3-embedding:4b", "30m", 1, 1024, "v1")


@pytest.mark.asyncio
async def test_embedding_adapter_returns_provider_neutral_valid_vector() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": "qwen3-embedding:4b", "digest": "sha256:test"}]},
            )
        payload = json.loads(request.content)
        assert payload["dimensions"] == 1024
        return httpx.Response(
            200,
            json={"model": "qwen3-embedding:4b", "embeddings": [[0.1] * 1024]},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:11434"
    )
    adapter = OllamaEmbeddingAdapter(_config(), client=client)
    batch = await adapter.embed(("hello",), "qwen3-embedding:4b", 1024)
    await client.aclose()
    assert batch.dimensions == 1024
    assert batch.model_digest == "sha256:test"
    assert len(batch.vectors[0]) == 1024


@pytest.mark.asyncio
async def test_embedding_adapter_rejects_dimension_drift() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "qwen3-embedding:4b", "embeddings": [[0.1] * 3]})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:11434"
    )
    adapter = OllamaEmbeddingAdapter(_config(), client=client)
    with pytest.raises(EmbeddingProviderError, match="ContractViolation"):
        await adapter.embed(("hello",), "qwen3-embedding:4b", 1024)
    await client.aclose()


@pytest.mark.asyncio
async def test_health_classifies_network_failure_without_provider_details() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic unavailable", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:11434"
    )
    adapter = OllamaEmbeddingAdapter(_config(), client=client, max_attempts=1)
    health = await adapter.health()
    await client.aclose()
    assert not health.available
    assert health.failure_class == "TransientProvider"


@pytest.mark.asyncio
async def test_embedding_contract_rejects_empty_text_and_wrong_model() -> None:
    client = httpx.AsyncClient(base_url="http://127.0.0.1:11434")
    adapter = OllamaEmbeddingAdapter(_config(), client=client)
    with pytest.raises(ValueError, match="non-empty"):
        await adapter.embed(("",), "qwen3-embedding:4b", 1024)
    with pytest.raises(ValueError, match="active index"):
        await adapter.embed(("hello",), "other", 1024)
    await client.aclose()
