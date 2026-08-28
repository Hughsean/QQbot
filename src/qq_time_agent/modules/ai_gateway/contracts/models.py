"""Provider-neutral structured model invocation contract."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ModelRoute(StrEnum):
    FAST = "FAST"
    REASONING = "REASONING"


def estimate_tokens(value: str) -> int:
    """Conservatively estimate tokens without a provider-specific tokenizer."""
    if not value:
        return 0
    cjk = sum("⺀" <= char <= "鿿" for char in value)
    other = len(value) - cjk
    return cjk + (other + 2) // 3


@dataclass(frozen=True, slots=True)
class TokenBudget:
    """Provider-neutral context-window limits carried with a model request."""

    max_context_tokens: int
    safety_margin_tokens: int = 0

    def __post_init__(self) -> None:
        if self.max_context_tokens < 1 or self.safety_margin_tokens < 0:
            raise ValueError("token budget values are invalid")
        if self.safety_margin_tokens >= self.max_context_tokens:
            raise ValueError("token budget safety margin must leave usable context")


@dataclass(frozen=True, slots=True)
class StructuredRequest:
    use_case: str
    prompt_version: str
    route: ModelRoute
    system_instruction: str
    external_data: str
    user_alias: str
    max_output_tokens: int = 1200
    token_budget: TokenBudget | None = None

    def __post_init__(self) -> None:
        if not self.use_case.strip() or not self.prompt_version.strip():
            raise ValueError("model use case and prompt version are required")
        if not self.system_instruction.strip() or not self.external_data.strip():
            raise ValueError("model instruction and external data are required")
        if not self.user_alias.strip() or self.max_output_tokens < 1:
            raise ValueError("safe user alias and positive output limit are required")
        if (
            self.token_budget is not None
            and self.max_output_tokens + self.token_budget.safety_margin_tokens
            >= self.token_budget.max_context_tokens
        ):
            raise ValueError("output reservation leaves no model input budget")


@dataclass(frozen=True, slots=True)
class StructuredResponse:
    output: Mapping[str, object]
    model: str
    input_tokens: int
    output_tokens: int


class ModelFailure(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


class StructuredModelPort(Protocol):
    async def invoke(self, request: StructuredRequest) -> StructuredResponse: ...
