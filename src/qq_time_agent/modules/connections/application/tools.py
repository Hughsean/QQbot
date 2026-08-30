"""Connections-owned Agent tool for provider-specific status queries."""

from collections.abc import Mapping

from qq_time_agent.contracts.tools import ToolDefinition
from qq_time_agent.modules.connections.application.status import ConnectionStatusQueryService
from qq_time_agent.modules.connections.contracts import ConnectionStatusView

_TOOL_NAME = "query_external_service_status"
_MAX_PROVIDER_PHRASE_LENGTH = 80


class ConnectionStatusToolRegistry:
    def __init__(self, query: ConnectionStatusQueryService) -> None:
        self._query = query
        self._definitions = (
            ToolDefinition(
                _TOOL_NAME,
                (
                    "Read the persisted status of an explicitly named external mail provider. "
                    "Copy the user's provider phrase verbatim, such as QQ邮箱 or Outlook; do not "
                    "replace it with a guessed provider. Generic phrases such as 邮箱 require "
                    "clarification. ACTIVE is saved connection metadata, not proof of current "
                    "IMAP, Graph, network, or account reachability. This tool does not authorize, "
                    "repair, retry, synchronize, or send reminders."
                ),
                {
                    "type": "object",
                    "properties": {
                        "provider": {
                            "type": "string",
                            "description": "The user's original provider phrase, copied verbatim.",
                        }
                    },
                    "required": ["provider"],
                    "additionalProperties": False,
                },
            ),
        )

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    async def call(self, owner_id: str, name: str, arguments: Mapping[str, object]) -> object:
        if name != _TOOL_NAME or set(arguments) != {"provider"}:
            raise ValueError("connection status tool request is invalid")
        provider = arguments.get("provider")
        if not isinstance(provider, str):
            raise ValueError("provider is required")
        phrase = " ".join(provider.strip().split())
        if not phrase:
            raise ValueError("provider is required")
        if len(phrase) > _MAX_PROVIDER_PHRASE_LENGTH:
            raise ValueError("provider is too long")
        snapshot = await self._query.query(owner_id, phrase)
        result: dict[str, object] = {
            "requested_provider": snapshot.requested_provider,
            "result": snapshot.result.value,
        }
        if snapshot.provider is None:
            result["available_providers"] = ["QQ_MAIL", "MICROSOFT"]
            return result
        result.update(
            {
                "provider": snapshot.provider,
                "status_source": "PERSISTED_CONNECTION_METADATA",
                "live_checked": False,
                "connection_count": len(snapshot.connections),
                "connections": [_serialize_connection(view) for view in snapshot.connections],
            }
        )
        return result


def _serialize_connection(view: ConnectionStatusView) -> dict[str, object]:
    # This explicit allow-list remains independent of credentials and provider internals.
    return {
        "connection_id": str(view.connection_id),
        "provider": view.provider,
        "status": view.status,
        "capabilities": list(view.capabilities),
        "account_mask": view.account_mask,
        "last_synced_at": (
            view.last_synced_at.isoformat() if view.last_synced_at is not None else None
        ),
        "display_label": view.display_label,
        "is_default": view.is_default,
        "sync_enabled": view.sync_enabled,
    }
