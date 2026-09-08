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
    """Shared whole-block admission policy used by direct and recovery runs.

    The fixed request components are counted before timeline/runtime blocks.  The
    values are provider-neutral estimates; adapters may perform a stricter
    preflight before sending the request.
    """

    max_context_tokens: int = 12_000
    mandatory_tokens: int = 0
    safety_margin_tokens: int = 256
    system_prompt_tokens: int = 0
    tool_schema_tokens: int = 0
    current_input_tokens: int = 0
    output_reserve_tokens: int = 0
    compression_threshold: float = 0.65

    def __post_init__(self) -> None:
        values = (
            self.max_context_tokens,
            self.mandatory_tokens,
            self.safety_margin_tokens,
            self.system_prompt_tokens,
            self.tool_schema_tokens,
            self.current_input_tokens,
            self.output_reserve_tokens,
        )
        if self.max_context_tokens < 1 or any(value < 0 for value in values[1:]):
            raise ValueError("context budget values are invalid")
        if not 0 < self.compression_threshold < 1:
            raise ValueError("compression threshold must be between zero and one")

    @property
    def fixed_tokens(self) -> int:
        return (
            self.mandatory_tokens
            + self.system_prompt_tokens
            + self.tool_schema_tokens
            + self.current_input_tokens
            + self.output_reserve_tokens
            + self.safety_margin_tokens
        )

    @property
    def usable_tokens(self) -> int:
        return self.max_context_tokens - self.fixed_tokens

    def admission(
        self, blocks: tuple[ContextBlock, ...] | list[ContextBlock]
    ) -> tuple[tuple[ContextBlock, ...], tuple[ContextBlock, ...], int]:
        """Return selected, dropped blocks, and their admitted token count."""
        selected = self.select(blocks)
        selected_ids = {item.identity for item in selected}
        dropped = tuple(item for item in blocks if item.identity not in selected_ids)
        return selected, dropped, sum(item.token_count for item in selected)

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
        used = self.fixed_tokens
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
