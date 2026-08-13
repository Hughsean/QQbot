"""Bounded Ollama adapter; provider DTOs are converted before return."""

import asyncio
import math
from collections.abc import Sequence

import httpx
from pydantic import BaseModel, ConfigDict

from qq_time_agent.bootstrap.config_models import OllamaConfig
from qq_time_agent.modules.embeddings.contracts import (
    EmbeddingBatch,
    EmbeddingError,
    EmbeddingProviderHealth,
)


class OllamaResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    embeddings: list[list[float]]


class OllamaModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    digest: str


class OllamaTagsResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    models: list[OllamaModel]


class EmbeddingProviderError(EmbeddingError):
    """Compatibility alias carrying the public embedding failure classification."""


class OllamaEmbeddingAdapter:
    def __init__(
        self,
        config: OllamaConfig,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 60.0,
        max_attempts: int = 2,
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            base_url=config.base_url, timeout=timeout_seconds
        )
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self._digest: str | None = None

    async def embed(self, texts: tuple[str, ...], model_id: str, dimensions: int) -> EmbeddingBatch:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("embedding input must contain non-empty text")
        self._validate_contract(model_id, dimensions)
        response = await self._request(texts, dimensions)
        vectors = self._validate_response(response, len(texts), dimensions)
        digest = await self._model_digest()
        return EmbeddingBatch(response.model, digest, dimensions, vectors)

    async def health(self) -> EmbeddingProviderHealth:
        try:
            batch = await self.embed(("health probe",), self._config.model, self._config.dimensions)
        except EmbeddingProviderError as exc:
            return EmbeddingProviderHealth(False, None, None, None, exc.failure_class)
        return EmbeddingProviderHealth(True, batch.model_id, batch.dimensions, batch.model_digest)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _validate_contract(self, model_id: str, dimensions: int) -> None:
        if model_id != self._config.model or dimensions != self._config.dimensions:
            raise ValueError("embedding request does not match active index contract")

    async def _request(self, texts: tuple[str, ...], dimensions: int) -> OllamaResponse:
        for attempt in range(self._max_attempts):
            try:
                raw = await self._client.post(
                    "/api/embed",
                    json={
                        "model": self._config.model,
                        "input": texts,
                        "dimensions": dimensions,
                        "keep_alive": self._config.keep_alive,
                    },
                )
                raw.raise_for_status()
                return OllamaResponse.model_validate(raw.json())
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt + 1 == self._max_attempts:
                    raise EmbeddingProviderError("TransientProvider") from exc
                await asyncio.sleep(0.1 * (attempt + 1))
            except (httpx.HTTPStatusError, ValueError) as exc:
                raise EmbeddingProviderError("PermanentProvider") from exc
        raise AssertionError("unreachable")

    async def _model_digest(self) -> str:
        if self._digest is not None:
            return self._digest
        try:
            raw = await self._client.get("/api/tags")
            raw.raise_for_status()
            tags = OllamaTagsResponse.model_validate(raw.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingProviderError("ContractViolation") from exc
        for model in tags.models:
            if model.name == self._config.model:
                if not model.digest.strip():
                    break
                self._digest = model.digest
                return model.digest
        raise EmbeddingProviderError("ContractViolation")

    @staticmethod
    def _validate_response(
        response: OllamaResponse, count: int, dimensions: int
    ) -> tuple[tuple[float, ...], ...]:
        if len(response.embeddings) != count:
            raise EmbeddingProviderError("ContractViolation")
        vectors = tuple(tuple(vector) for vector in response.embeddings)
        if not _vectors_are_valid(vectors, dimensions):
            raise EmbeddingProviderError("ContractViolation")
        return vectors


def _vectors_are_valid(vectors: Sequence[Sequence[float]], dimensions: int) -> bool:
    return all(
        len(vector) == dimensions and all(math.isfinite(value) for value in vector)
        for vector in vectors
    )
