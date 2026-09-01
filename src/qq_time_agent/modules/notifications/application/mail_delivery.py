"""Deterministic owner-rule override for mail delivery."""

from qq_time_agent.modules.agent.contracts import AgentDelivery
from qq_time_agent.modules.identity.contracts import (
    MailRuleAction,
    MailRuleMatchField,
    MailRuleQueryPort,
    MailRuleView,
)


class MailDeliveryPolicy:
    def __init__(self, rules: MailRuleQueryPort) -> None:
        self._rules = rules

    async def resolve(
        self, user_id: str, sender: str, subject: str, model_delivery: AgentDelivery
    ) -> AgentDelivery:
        sender_value = sender.casefold()
        subject_value = subject.casefold()
        matches = [
            rule
            for rule in await self._rules.list_mail_rules(user_id)
            if rule.pattern.casefold()
            in (
                sender_value
                if rule.match_field is MailRuleMatchField.SENDER
                else subject_value
            )
        ]
        if not matches:
            return model_delivery
        rule = min(matches, key=_priority)
        return (
            AgentDelivery.NOTIFY
            if rule.action is MailRuleAction.NOTIFY
            else AgentDelivery.HOLD
        )


def _priority(rule: MailRuleView) -> tuple[int, int, int, str, str]:
    """Specific sender rules win; exact ties prefer NOTIFY and remain stable."""
    return (
        -len(rule.pattern.casefold()),
        0 if rule.match_field is MailRuleMatchField.SENDER else 1,
        0 if rule.action is MailRuleAction.NOTIFY else 1,
        rule.pattern.casefold(),
        str(rule.rule_id),
    )
