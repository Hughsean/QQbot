from dataclasses import dataclass

import pytest

from qq_time_agent.modules.agent.application.budget import (
    ContextBlock,
    ContextBudgetExceeded,
    ContextBudgetPolicy,
    estimate_tokens,
)


@dataclass(frozen=True)
class Case:
    content: str
    minimum: int


@pytest.mark.parametrize(
    "case",
    [Case("plain ascii json", 5), Case("今天处理日程", 6), Case('{"value":"明天"}', 5)],
)
def test_token_estimator_is_conservative_for_cjk_and_json(case: Case) -> None:
    assert estimate_tokens(case.content) >= case.minimum


def test_budget_keeps_whole_blocks_by_priority_and_deduplicates_order() -> None:
    high = ContextBlock("agenda", "active", "A" * 30, 100, stable_id="agenda")
    medium = ContextBlock("retrieval", "knowledge", "B" * 30, 80, stable_id="knowledge")
    low = ContextBlock("history", "old", "C" * 90, 10, stable_id="old")
    policy = ContextBudgetPolicy(max_context_tokens=30, safety_margin_tokens=2)

    selected = policy.select([low, medium, high])

    assert [item.stable_id for item in selected] == ["agenda", "knowledge"]
    assert policy.render([low, medium, high]) == high.content + "\n\n" + medium.content


def test_budget_fails_closed_when_mandatory_context_does_not_fit() -> None:
    mandatory = ContextBlock("system", "current", "必须保留" * 20, 100, mandatory=True)
    with pytest.raises(ContextBudgetExceeded, match="mandatory"):
        ContextBudgetPolicy(max_context_tokens=10).select([mandatory])


def test_budget_admission_reserves_fixed_request_components() -> None:
    policy = ContextBudgetPolicy(
        max_context_tokens=30,
        system_prompt_tokens=4,
        tool_schema_tokens=3,
        current_input_tokens=5,
        output_reserve_tokens=6,
        safety_margin_tokens=2,
    )
    selected, dropped, tokens = policy.admission(
        [
            ContextBlock("timeline", "recent", "R" * 24, 100, mandatory=True),
            ContextBlock("timeline", "old", "O" * 24, 10),
        ]
    )

    assert [item.label for item in selected] == ["recent"]
    assert [item.label for item in dropped] == ["old"]
    assert tokens == selected[0].token_count
    assert policy.usable_tokens == 10


def test_budget_rejects_mandatory_timeline_after_fixed_reservations() -> None:
    policy = ContextBudgetPolicy(max_context_tokens=20, output_reserve_tokens=8)
    mandatory = ContextBlock("timeline", "recent", "必须保留" * 8, 100, mandatory=True)
    with pytest.raises(ContextBudgetExceeded, match="mandatory"):
        policy.select([mandatory])


def test_budget_compression_threshold_is_validated() -> None:
    with pytest.raises(ValueError, match="compression threshold"):
        ContextBudgetPolicy(compression_threshold=1.0)


    first = ContextBlock("history", "one", "first", 10, stable_id="a")
    second = ContextBlock("history", "two", "second", 10, stable_id="b")
    policy = ContextBudgetPolicy(max_context_tokens=20, safety_margin_tokens=0)
    assert policy.select([second, first]) == (first, second)
