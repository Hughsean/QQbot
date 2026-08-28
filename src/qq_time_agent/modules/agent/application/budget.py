"""Deterministic token-budget primitives for model-facing Agent context."""

from dataclasses import dataclass
from hashlib import sha256

from qq_time_agent.modules.ai_gateway.contracts import estimate_tokens


class ContextBudgetExceeded(ValueError):
    """The mandatory model context cannot fit within the configured budget."""


@dataclass(frozen=True, slots=True)
class ContextBlock:
    """An indivisible optional or mandatory context unit."""

    source: str
    label: str
    content: str
    priority: int
    relevance: float = 0.0
    recency: int = 0
    stable_id: str = ""
    mandatory: bool = False

    @property
    def token_count(self) -> int:
        return estimate_tokens(self.content)

    @property
    def identity(self) -> str:
        return self.stable_id or sha256(self.content.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ContextBudgetPolicy:
    """Shared whole-block admission policy used by direct and recovery runs."""

    max_context_tokens: int = 12_000
    mandatory_tokens: int = 0
    safety_margin_tokens: int = 256

    def __post_init__(self) -> None:
        if (
            self.max_context_tokens < 1
            or self.mandatory_tokens < 0
            or self.safety_margin_tokens < 0
        ):
            raise ValueError("context budget values are invalid")

    def select(
        self, blocks: tuple[ContextBlock, ...] | list[ContextBlock]
    ) -> tuple[ContextBlock, ...]:
        ordered = sorted(
            blocks,
            key=lambda item: (
                -item.mandatory,
                -item.priority,
                -item.relevance,
                -item.recency,
                item.identity,
            ),
        )
        selected: list[ContextBlock] = []
        used = self.mandatory_tokens + self.safety_margin_tokens
        for block in ordered:
            if block.mandatory:
                selected.append(block)
                used += block.token_count
        if used > self.max_context_tokens:
            raise ContextBudgetExceeded("mandatory Agent context exceeds token budget")
        for block in ordered:
            if block.mandatory:
                continue
            if used + block.token_count <= self.max_context_tokens:
                selected.append(block)
                used += block.token_count
        return tuple(selected)

    def render(self, blocks: tuple[ContextBlock, ...] | list[ContextBlock]) -> str:
        return "\n\n".join(block.content for block in self.select(blocks))
