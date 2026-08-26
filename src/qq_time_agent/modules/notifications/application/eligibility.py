"""Revalidate mutable Agenda, Connection, and preference facts before delivery."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from qq_time_agent.modules.agenda.contracts import (
    AgendaConflictView,
    AgendaNotificationItem,
    AgendaNotificationQueryPort,
)
from qq_time_agent.modules.connections.contracts import ConnectionNotificationQueryPort
from qq_time_agent.modules.identity.contracts import UserPreferencesPort
from qq_time_agent.modules.notifications.application.rendering import (
    render_conflict,
    render_digest,
)
from qq_time_agent.modules.notifications.domain.models import NotificationIntent, NotificationKind
from qq_time_agent.modules.notifications.domain.policy import next_allowed_at


class NotificationSourceEligibilityService:
    def __init__(
        self,
        preferences: UserPreferencesPort,
        agenda: AgendaNotificationQueryPort,
        connections: ConnectionNotificationQueryPort,
    ) -> None:
        self._preferences = preferences
        self._agenda = agenda
        self._connections = connections

    async def eligible_at(self, intent: NotificationIntent, now: datetime) -> datetime | None:
        preferences = await self._preferences.get_preferences(intent.draft.user_id)
        eligible = False
        if intent.draft.kind is NotificationKind.DAILY_DIGEST:
            eligible = preferences.digest_enabled and await self._digest_matches(
                intent, preferences.timezone, now
            )
        elif intent.draft.kind is NotificationKind.AGENDA_CONFLICT:
            eligible = preferences.conflict_notifications_enabled and await self._conflict_matches(
                intent, preferences.timezone, now
            )
        elif intent.draft.kind is NotificationKind.CONNECTION_REAUTH:
            eligible = preferences.reauth_notifications_enabled and await self._reauth_matches(
                intent
            )
        elif intent.draft.kind is NotificationKind.AGENT_RESULT:
            eligible = True
        return next_allowed_at(now, preferences) if eligible else None

    async def _digest_matches(
        self, intent: NotificationIntent, timezone: str, now: datetime
    ) -> bool:
        try:
            day = date.fromisoformat(intent.draft.idempotency_key.split(":")[-2])
        except ValueError:
            return False
        zone = ZoneInfo(timezone)
        if now.astimezone(zone).date() != day:
            return False
        start = datetime.combine(day, time.min, tzinfo=zone)
        end = start + timedelta(days=1)
        entries = await self._agenda.list_active(start.astimezone(UTC), end.astimezone(UTC))
        local = tuple(_local(value, zone) for value in entries)
        return render_digest(day, local) == intent.draft.content

    async def _conflict_matches(
        self, intent: NotificationIntent, timezone: str, now: datetime
    ) -> bool:
        parts = intent.draft.subject_key.split(":")
        if len(parts) != 5:
            return False
        try:
            ids = (UUID(parts[1]), UUID(parts[3]))
            versions = (int(parts[2].removeprefix("v")), int(parts[4].removeprefix("v")))
        except ValueError:
            return False
        values = await self._agenda.get_items(ids)
        if len(values) != 2 or tuple(value.version for value in values) != versions:
            return False
        first, second = values
        if first.ends_at <= now and second.ends_at <= now:
            return False
        if not (first.starts_at < second.ends_at and second.starts_at < first.ends_at):
            return False
        zone = ZoneInfo(timezone)
        return (
            render_conflict(AgendaConflictView(_local(first, zone), _local(second, zone)))
            == intent.draft.content
        )

    async def _reauth_matches(self, intent: NotificationIntent) -> bool:
        parts = intent.draft.subject_key.split(":")
        if len(parts) != 4:
            return False
        try:
            connection_id = UUID(parts[1])
            epoch = int(parts[3])
        except ValueError:
            return False
        return await self._connections.is_reauth_episode(intent.draft.user_id, connection_id, epoch)


def _local(value: AgendaNotificationItem, zone: ZoneInfo) -> AgendaNotificationItem:
    return AgendaNotificationItem(
        value.agenda_entry_id,
        value.version,
        value.title,
        value.starts_at.astimezone(zone),
        value.ends_at.astimezone(zone),
        value.kind,
    )
