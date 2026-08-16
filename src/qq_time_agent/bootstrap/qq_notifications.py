"""QQ-process composition for persistent notification delivery."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.adapters.inbound.qq.gateway import OfficialQqGateway
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.agenda.application.notification_query import (
    AgendaNotificationQueryService,
)
from qq_time_agent.modules.agenda.application.ports import AgendaRepository
from qq_time_agent.modules.connections.application.notification_query import (
    ConnectionNotificationQueryService,
)
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.identity.contracts import UserPreferencesPort
from qq_time_agent.modules.notifications.application.eligibility import (
    NotificationSourceEligibilityService,
)
from qq_time_agent.modules.notifications.application.intent_delivery import (
    NotificationIntentDeliveryService,
)
from qq_time_agent.modules.notifications.application.service import NotificationService
from qq_time_agent.modules.notifications.infrastructure.repository import (
    SqlDeliveryRepository,
    SqlNotificationIntentRepository,
)


def build_qq_notification_services(
    sessions: async_sessionmaker[AsyncSession],
    preferences: UserPreferencesPort,
    agenda_repository: AgendaRepository,
    gateway: OfficialQqGateway,
    clock: Clock,
) -> tuple[NotificationService, NotificationIntentDeliveryService]:
    agenda = AgendaNotificationQueryService(agenda_repository)
    connections = ConnectionNotificationQueryService(SqlConnectionRepository(sessions))
    return (
        NotificationService(gateway, SqlDeliveryRepository(sessions), clock),
        NotificationIntentDeliveryService(
            SqlNotificationIntentRepository(sessions),
            NotificationSourceEligibilityService(preferences, agenda, connections),
            gateway,
            "qq-notification-intents",
        ),
    )
