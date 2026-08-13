"""Public connection query contracts."""

from qq_time_agent.modules.connections.contracts.sync import ConnectionSyncPort, MailAccessGrant
from qq_time_agent.modules.connections.contracts.views import ConnectionStatusView

__all__ = ["ConnectionStatusView", "ConnectionSyncPort", "MailAccessGrant"]
