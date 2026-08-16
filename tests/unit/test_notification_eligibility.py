from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaConflictView, AgendaNotificationItem
from qq_time_agent.modules.connections.contracts import ReauthReminderCandidate
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.notifications.application.eligibility import (
    NotificationSourceEligibilityService,
)
from qq_time_agent.modules.notifications.application.rendering import render_digest
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntent,
    NotificationIntentDraft,
    NotificationKind,
)

NOW = datetime(2026, 8, 15, 1, tzinfo=UTC)


@dataclass
class Preferences:
    async def get_preferences(self, user_id: str) -> UserPreferencesView:
        return UserPreferencesView(
            user_id, "UTC", time(9), time(18), time(12), time(13), (0, 1, 2, 3, 4), 60, 30
        )


@dataclass
class Agenda:
    values: tuple[AgendaNotificationItem, ...]

    async def list_active(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaNotificationItem, ...]:
        return self.values

    async def list_conflicts(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaConflictView, ...]:
        return ()

    async def get_items(self, entry_ids: tuple[UUID, ...]) -> tuple[AgendaNotificationItem, ...]:
        by_id = {value.agenda_entry_id: value for value in self.values}
        return tuple(by_id[value] for value in entry_ids if value in by_id)


@dataclass
class Connections:
    active: bool

    async def list_reauth_required(self, user_id: str) -> tuple[ReauthReminderCandidate, ...]:
        return ()

    async def is_reauth_episode(self, user_id: str, connection_id: UUID, reauth_epoch: int) -> bool:
        return self.active


def _intent(kind: NotificationKind, subject: str, key: str, content: str) -> NotificationIntent:
    return NotificationIntent.create(
        NotificationIntentDraft("owner", kind, subject, key, "notification-v1", content, NOW),
        NOW,
    )


@pytest.mark.asyncio
async def test_recovered_connection_invalidates_pending_reauth() -> None:
    value = _intent(
        NotificationKind.CONNECTION_REAUTH,
        f"reauth:{uuid4()}:episode:2",
        "reauth-key",
        "reauth",
    )
    service = NotificationSourceEligibilityService(Preferences(), Agenda(()), Connections(False))
    assert not await service.eligible_at(value, NOW)


@pytest.mark.asyncio
async def test_deleted_agenda_entry_invalidates_pending_digest() -> None:
    item = AgendaNotificationItem(
        uuid4(),
        1,
        "Meeting",
        datetime(2026, 8, 15, 2, tzinfo=UTC),
        datetime(2026, 8, 15, 3, tzinfo=UTC),
        "EVENT",
    )
    value = _intent(
        NotificationKind.DAILY_DIGEST,
        "daily-digest:owner",
        "daily-digest:owner:2026-08-15:notification-v1",
        render_digest(date(2026, 8, 15), (item,)),
    )
    service = NotificationSourceEligibilityService(Preferences(), Agenda(()), Connections(True))
    assert not await service.eligible_at(value, NOW)
