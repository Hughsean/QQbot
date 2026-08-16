"""Credential-free application mapping for connection views."""

from qq_time_agent.modules.connections.contracts import ConnectionStatusView
from qq_time_agent.modules.connections.domain.models import ExternalConnection


def to_connection_view(connection: ExternalConnection) -> ConnectionStatusView:
    return ConnectionStatusView(
        connection.connection_id,
        connection.provider.value,
        connection.status.value,
        tuple(sorted(connection.capabilities)),
        connection.account_mask,
        connection.last_synced_at,
        connection.display_label,
        connection.is_default,
        connection.sync_enabled,
    )
