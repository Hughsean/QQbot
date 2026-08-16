"""Worker-only composition for deterministic notification planning."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.agenda.application.notification_query import (
    AgendaNotificationQueryService,
)
from qq_time_agent.modules.agenda.application.ports import AgendaRepository
from qq_time_agent.modules.connections.application.notification_query import (
    ConnectionNotificationQueryService,
)
from qq_time_agent.modules.connections.infrastructure.repository import SqlConnectionRepository
from qq_time_agent.modules.identity.contracts import UserPreferencesPort
from qq_time_agent.modules.notifications.application.planning import NotificationPlanningService
from qq_time_agent.modules.notifications.infrastructure.repository import (
    SqlNotificationIntentRepository,
)


def build_notification_planner(
    sessions: async_sessionmaker[AsyncSession],
    preferences: UserPreferencesPort,
    agenda_repository: AgendaRepository,
) -> NotificationPlanningService:
    return NotificationPlanningService(
        SqlNotificationIntentRepository(sessions),
        preferences,
        AgendaNotificationQueryService(agenda_repository),
        ConnectionNotificationQueryService(SqlConnectionRepository(sessions)),
    )
