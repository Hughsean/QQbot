"""Public connection query contracts."""

from qq_time_agent.modules.connections.contracts.sync import (
    ConnectionSyncPort,
    ConnectionUnavailableError,
    MailAccessGrant,
)
from qq_time_agent.modules.connections.contracts.views import (
    ConnectionNotificationQueryPort,
    ConnectionStatusView,
    ReauthReminderCandidate,
)

__all__ = [
    "ConnectionNotificationQueryPort",
    "ConnectionStatusView",
    "ConnectionSyncPort",
    "ConnectionUnavailableError",
    "MailAccessGrant",
    "ReauthReminderCandidate",
]
