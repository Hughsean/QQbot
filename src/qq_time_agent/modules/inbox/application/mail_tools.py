"""Inbox-owned read-only recent mail Agent tool."""

from collections.abc import Mapping

from qq_time_agent.contracts.tools import ToolCallContext, ToolDefinition
from qq_time_agent.modules.inbox.contracts import RecentMailQueryPort

_NAME = "find_recent_mail"


class RecentMailToolRegistry:
    def __init__(self, query: RecentMailQueryPort) -> None:
        self._query = query
        self._definitions = (
            ToolDefinition(
                _NAME,
                "Read bounded recent mail metadata from Inbox; this is read-only T2 evidence.",
                {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "additionalProperties": False,
                },
            ),
        )

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    async def call(
        self,
        owner_id: str,
        name: str,
        arguments: Mapping[str, object],
        context: ToolCallContext,
    ) -> object:
        del context
        if name != _NAME or set(arguments) - {"keyword", "limit"}:
            raise ValueError("recent mail tool request is invalid")
        keyword = arguments.get("keyword")
        limit = arguments.get("limit", 10)
        if keyword is not None and not isinstance(keyword, str):
            raise ValueError("keyword must be text")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        items = await self._query.list_recent_mail(owner_id, limit, keyword)
        return {
            "source": "INBOX_PERSISTED_METADATA",
            "trust_level": "T2",
            "items": [
                {
                    "inbox_item_id": str(item.inbox_item_id),
                    "source_type": item.source_type,
                    "subject": item.subject,
                    "sender": item.sender_mask,
                    "occurred_at": item.occurred_at.isoformat(),
                    "status": item.status,
                    "deleted": item.deleted,
                }
                for item in items
            ],
        }
