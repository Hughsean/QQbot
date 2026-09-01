"""Owner-controlled mail notification rule contracts."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class MailRuleMatchField(StrEnum):
    SENDER = "SENDER"
    SUBJECT = "SUBJECT"


class MailRuleAction(StrEnum):
    NOTIFY = "NOTIFY"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class MailRuleView:
    rule_id: UUID
    match_field: MailRuleMatchField
    pattern: str
    action: MailRuleAction


class MailRuleQueryPort(Protocol):
    async def list_mail_rules(self, user_id: str) -> tuple[MailRuleView, ...]: ...


class MailRuleCommandPort(Protocol):
    async def register_mail_rule(
        self,
        user_id: str,
        match_field: MailRuleMatchField,
        pattern: str,
        action: MailRuleAction,
    ) -> MailRuleView: ...
