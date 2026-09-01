"""Owner-authorized mail notification rule application service."""

from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.identity.application.ports import MailRuleRepository
from qq_time_agent.modules.identity.contracts import (
    MailRuleAction,
    MailRuleCommandPort,
    MailRuleMatchField,
    MailRuleQueryPort,
    MailRuleView,
)


class MailRuleService(MailRuleCommandPort, MailRuleQueryPort):
    def __init__(
        self, repository: MailRuleRepository, clock: Clock, owner_id: str = "owner"
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._owner_id = owner_id

    async def list_mail_rules(self, user_id: str) -> tuple[MailRuleView, ...]:
        self._authorize(user_id)
        return await self._repository.list(user_id)

    async def register_mail_rule(
        self,
        user_id: str,
        match_field: MailRuleMatchField,
        pattern: str,
        action: MailRuleAction,
    ) -> MailRuleView:
        self._authorize(user_id)
        value = " ".join(pattern.split())
        if not value or len(value) > 240:
            raise ValueError("mail rule pattern is invalid")
        return await self._repository.add_or_get(
            user_id, match_field, value, value.casefold(), action, self._clock.now()
        )

    def _authorize(self, user_id: str) -> None:
        if user_id != self._owner_id:
            raise PermissionError("mail rule is not authorized")
