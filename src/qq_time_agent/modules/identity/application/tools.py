"""Identity-owned Agent tool for owner group-chat aliases."""

from collections.abc import Mapping

from qq_time_agent.contracts.tools import ToolCallContext, ToolDefinition
from qq_time_agent.modules.identity.contracts import (
    MailRuleAction,
    MailRuleCommandPort,
    MailRuleMatchField,
    OwnerGroupAliasCommandPort,
)

_TOOL_NAME = "register_owner_group_alias"
_MAIL_TOOL_NAME = "register_mail_rule"


class OwnerGroupAliasToolRegistry:
    def __init__(
        self,
        aliases: OwnerGroupAliasCommandPort,
        mail_rules: MailRuleCommandPort | None = None,
    ) -> None:
        self._aliases = aliases
        self._mail_rules = mail_rules
        self._definitions = (
            ToolDefinition(
                _TOOL_NAME,
                "Register an owner-declared display name for forwarded group-chat attribution.",
                {
                    "type": "object",
                    "properties": {"alias": {"type": "string"}},
                    "required": ["alias"],
                },
            ),
            *(() if mail_rules is None else (_mail_rule_definition(),)),
        )

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    async def call(
        self,
        owner_id: str,
        name: str,
        arguments: Mapping[str, object],
        context: ToolCallContext | None = None,
    ) -> object:
        if name == _MAIL_TOOL_NAME:
            if context is None or context.source_type != "QQ_DIRECT":
                raise PermissionError("mail rules require a direct owner message")
            return await self._register_mail_rule(owner_id, arguments)
        if name != _TOOL_NAME or set(arguments) != {"alias"}:
            raise ValueError("identity tool request is invalid")
        alias = arguments.get("alias")
        if not isinstance(alias, str):
            raise ValueError("alias is required")
        result = await self._aliases.register_owner_group_alias(owner_id, alias)
        return {"alias": result.alias, "status": "REGISTERED"}

    async def _register_mail_rule(
        self, owner_id: str, arguments: Mapping[str, object]
    ) -> object:
        if self._mail_rules is None or set(arguments) != {"match_field", "pattern", "action"}:
            raise ValueError("mail rule tool is unavailable or invalid")
        field = arguments.get("match_field")
        pattern = arguments.get("pattern")
        action = arguments.get("action")
        if (
            not isinstance(field, str)
            or not isinstance(pattern, str)
            or not isinstance(action, str)
        ):
            raise ValueError("mail rule fields are required")
        try:
            rule = await self._mail_rules.register_mail_rule(
                owner_id, MailRuleMatchField(field), pattern, MailRuleAction(action)
            )
        except ValueError as exc:
            raise ValueError("mail rule values are invalid") from exc
        return {
            "rule_id": str(rule.rule_id),
            "match_field": rule.match_field.value,
            "pattern": rule.pattern,
            "action": rule.action.value,
            "status": "REGISTERED",
        }


def _mail_rule_definition() -> ToolDefinition:
    return ToolDefinition(
        _MAIL_TOOL_NAME,
        "Register an owner mail notification rule; exact field and action are required.",
        {
            "type": "object",
            "properties": {
                "match_field": {"type": "string", "enum": ["SENDER", "SUBJECT"]},
                "pattern": {"type": "string"},
                "action": {"type": "string", "enum": ["NOTIFY", "HOLD"]},
            },
            "required": ["match_field", "pattern", "action"],
            "additionalProperties": False,
        },
    )
