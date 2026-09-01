from uuid import UUID

import pytest

from qq_time_agent.modules.agent.contracts import AgentDelivery
from qq_time_agent.modules.identity.contracts import (
    MailRuleAction,
    MailRuleMatchField,
    MailRuleView,
)
from qq_time_agent.modules.notifications.application.mail_delivery import MailDeliveryPolicy


class Rules:
    def __init__(self, values: tuple[MailRuleView, ...]) -> None:
        self.values = values

    async def list_mail_rules(self, user_id: str) -> tuple[MailRuleView, ...]:
        assert user_id == "owner"
        return self.values


def rule(
    number: int,
    field: MailRuleMatchField,
    pattern: str,
    action: MailRuleAction,
) -> MailRuleView:
    return MailRuleView(UUID(int=number), field, pattern, action)


@pytest.mark.asyncio
async def test_policy_matches_normalized_full_sender_and_subject() -> None:
    policy = MailDeliveryPolicy(
        Rules((rule(1, MailRuleMatchField.SENDER, "Example.COM", MailRuleAction.NOTIFY),))
    )
    result = await policy.resolve("owner", "  person@example.com ", "Update", AgentDelivery.HOLD)
    assert result is AgentDelivery.NOTIFY


@pytest.mark.asyncio
async def test_specific_pattern_beats_broad_pattern() -> None:
    policy = MailDeliveryPolicy(
        Rules(
            (
                rule(1, MailRuleMatchField.SENDER, "example.com", MailRuleAction.HOLD),
                rule(2, MailRuleMatchField.SENDER, "person@example.com", MailRuleAction.NOTIFY),
            )
        )
    )
    assert (
        await policy.resolve("owner", "person@example.com", "", AgentDelivery.HOLD)
    ) is AgentDelivery.NOTIFY


@pytest.mark.asyncio
async def test_sender_beats_subject_and_notify_beats_hold_on_ties() -> None:
    policy = MailDeliveryPolicy(
        Rules(
            (
                rule(1, MailRuleMatchField.SUBJECT, "invoice", MailRuleAction.NOTIFY),
                rule(2, MailRuleMatchField.SENDER, "invoice", MailRuleAction.HOLD),
                rule(3, MailRuleMatchField.SENDER, "invoice", MailRuleAction.NOTIFY),
            )
        )
    )
    assert (
        await policy.resolve("owner", "invoice", "invoice", AgentDelivery.HOLD)
    ) is AgentDelivery.NOTIFY


@pytest.mark.asyncio
async def test_policy_preserves_model_delivery_without_match() -> None:
    policy = MailDeliveryPolicy(Rules(()))
    assert (
        await policy.resolve("owner", "person@example.com", "hello", AgentDelivery.HOLD)
    ) is AgentDelivery.HOLD
