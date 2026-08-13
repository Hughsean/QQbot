"""Provider-neutral embedding contract."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    model_id: str
    model_digest: str
    dimensions: int
    vectors: tuple[tuple[float, ...], ...]


@dataclass(frozen=True, slots=True)
class EmbeddingProviderHealth:
    available: bool
    model_id: str | None
    dimensions: int | None
    model_digest: str | None = None
    failure_class: str | None = None


class EmbeddingError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


class EmbeddingPort(Protocol):
    async def embed(
        self, texts: tuple[str, ...], model_id: str, dimensions: int
    ) -> EmbeddingBatch: ...

    async def health(self) -> EmbeddingProviderHealth: ...
