"""Deterministic Stage 15 notification intent planning."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from qq_time_agent.modules.agenda.contracts import (
    AgendaConflictView,
    AgendaNotificationItem,
    AgendaNotificationQueryPort,
)
from qq_time_agent.modules.connections.contracts import ConnectionNotificationQueryPort
from qq_time_agent.modules.identity.contracts import UserPreferencesPort, UserPreferencesView
from qq_time_agent.modules.notifications.application.ports import NotificationIntentRepository
from qq_time_agent.modules.notifications.application.rendering import (
    TEMPLATE_VERSION,
    conflict_key,
    render_conflict,
    render_digest,
    render_reauth,
)
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntentDraft,
    NotificationKind,
)
from qq_time_agent.modules.notifications.domain.policy import next_allowed_at


class NotificationPlanningService:
    def __init__(
        self,
        repository: NotificationIntentRepository,
        preferences: UserPreferencesPort,
        agenda: AgendaNotificationQueryPort,
        connections: ConnectionNotificationQueryPort,
    ) -> None:
        self._repository = repository
        self._preferences = preferences
        self._agenda = agenda
        self._connections = connections

    async def plan(self, user_id: str, now: datetime) -> int:
        preferences = await self._preferences.get_preferences(user_id)
        count = 0
        if preferences.digest_enabled:
            count += await self._plan_digest(user_id, now, preferences)
        if preferences.conflict_notifications_enabled:
            count += await self._plan_conflicts(user_id, now, preferences)
        if preferences.reauth_notifications_enabled:
            count += await self._plan_reauth(user_id, now, preferences)
        return count

    async def _plan_digest(
        self, user_id: str, now: datetime, preferences: UserPreferencesView
    ) -> int:
        zone = ZoneInfo(preferences.timezone)
        local = now.astimezone(zone)
        if local.timetz().replace(tzinfo=None) < preferences.digest_local_time:
            return 0
        start = datetime.combine(local.date(), time.min, tzinfo=zone)
        end = start + timedelta(days=1)
        entries = _local_entries(
            await self._agenda.list_active(start.astimezone(UTC), end.astimezone(UTC)), zone
        )
        key = f"daily-digest:{user_id}:{local.date().isoformat()}:{TEMPLATE_VERSION}"
        await self._repository.add_or_get(
            NotificationIntentDraft(
                user_id,
                NotificationKind.DAILY_DIGEST,
                f"daily-digest:{user_id}",
                key,
                TEMPLATE_VERSION,
                render_digest(local.date(), entries),
                next_allowed_at(now, preferences),
            ),
            now,
        )
        return 1

    async def _plan_conflicts(
        self, user_id: str, now: datetime, preferences: UserPreferencesView
    ) -> int:
        zone = ZoneInfo(preferences.timezone)
        values = await self._agenda.list_conflicts(now, now + timedelta(days=30))
        for value in values:
            local = AgendaConflictView(
                _local_entry(value.first, zone), _local_entry(value.second, zone)
            )
            key = conflict_key(local)
            await self._repository.add_or_get(
                NotificationIntentDraft(
                    user_id,
                    NotificationKind.AGENDA_CONFLICT,
                    key.removesuffix(f":{TEMPLATE_VERSION}"),
                    key,
                    TEMPLATE_VERSION,
                    render_conflict(local),
                    next_allowed_at(now, preferences),
                ),
                now,
            )
        return len(values)

    async def _plan_reauth(
        self, user_id: str, now: datetime, preferences: UserPreferencesView
    ) -> int:
        values = await self._connections.list_reauth_required(user_id)
        count = 0
        for value in values:
            subject = f"reauth:{value.connection_id}:episode:{value.reauth_epoch}"
            if await self._repository.has_open(subject) or await self._repository.has_recent_sent(
                subject, now - timedelta(hours=24)
            ):
                continue
            bucket = max(0, int((now - value.required_since).total_seconds() // 86400))
            await self._repository.add_or_get(
                NotificationIntentDraft(
                    user_id,
                    NotificationKind.CONNECTION_REAUTH,
                    subject,
                    f"{subject}:day:{bucket}:{TEMPLATE_VERSION}",
                    TEMPLATE_VERSION,
                    render_reauth(value),
                    next_allowed_at(now, preferences),
                ),
                now,
            )
            count += 1
        return count


def _local_entries(
    values: tuple[AgendaNotificationItem, ...], zone: ZoneInfo
) -> tuple[AgendaNotificationItem, ...]:
    return tuple(_local_entry(value, zone) for value in values)


def _local_entry(value: AgendaNotificationItem, zone: ZoneInfo) -> AgendaNotificationItem:
    return AgendaNotificationItem(
        value.agenda_entry_id,
        value.version,
        value.title,
        value.starts_at.astimezone(zone),
        value.ends_at.astimezone(zone),
        value.kind,
    )
