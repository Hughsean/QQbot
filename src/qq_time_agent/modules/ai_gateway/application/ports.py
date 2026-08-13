"""AI invocation metadata persistence port."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class InvocationMetadata:
    invocation_id: UUID
    use_case: str
    prompt_version: str
    route: str
    model: str | None
    status: str
    failure_class: str | None
    input_tokens: int
    output_tokens: int
    started_at: datetime
    completed_at: datetime
    latency_ms: int


class InvocationRepository(Protocol):
    async def add(self, metadata: InvocationMetadata) -> None: ...
