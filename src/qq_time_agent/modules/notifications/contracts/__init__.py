"""Public Notification contracts."""

from qq_time_agent.modules.notifications.contracts.agent_results import (
    AgentMailResultRequest,
    MailNotificationSource,
    NotificationIntentCommandPort,
)
from qq_time_agent.modules.notifications.contracts.models import (
    DeliveryRef,
    NotificationIntentMetrics,
    NotificationMetricsPort,
    NotificationPort,
    NotificationPreSendPermanentError,
    NotificationPreSendTransientError,
    NotificationSender,
)

__all__ = [
    "AgentMailResultRequest",
    "DeliveryRef",
    "MailNotificationSource",
    "NotificationIntentCommandPort",
    "NotificationIntentMetrics",
    "NotificationMetricsPort",
    "NotificationPort",
    "NotificationPreSendPermanentError",
    "NotificationPreSendTransientError",
    "NotificationSender",
]
