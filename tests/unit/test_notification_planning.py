from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import (
    AgendaConflictView,
    AgendaNotificationItem,
)
from qq_time_agent.modules.connections.contracts import ReauthReminderCandidate
from qq_time_agent.modules.identity.contracts import UserPreferencesView
from qq_time_agent.modules.notifications.application.planning import NotificationPlanningService
from qq_time_agent.modules.notifications.domain.models import (
    NotificationIntent,
    NotificationIntentDraft,
)

NOW = datetime(2026, 8, 15, 1, tzinfo=UTC)


@dataclass
class Preferences:
    async def get_preferences(self, user_id: str) -> UserPreferencesView:
        return UserPreferencesView(
            user_id,
            "Asia/Shanghai",
            time(9),
            time(18),
            time(12),
            time(13),
            (0, 1, 2, 3, 4),
            60,
            30,
            quiet_hours_enabled=False,
        )


@dataclass
class Agenda:
    version: int = 1
    first_id: UUID = field(default_factory=uuid4)
    second_id: UUID = field(default_factory=uuid4)

    def entries(self) -> tuple[AgendaNotificationItem, AgendaNotificationItem]:
        return (
            AgendaNotificationItem(
                self.first_id,
                self.version,
                "Focus",
                datetime(2026, 8, 15, 2, tzinfo=UTC),
                datetime(2026, 8, 15, 3, tzinfo=UTC),
                "EVENT",
            ),
            AgendaNotificationItem(
                self.second_id,
                1,
                "Meeting",
                datetime(2026, 8, 15, 2, 30, tzinfo=UTC),
                datetime(2026, 8, 15, 3, 30, tzinfo=UTC),
                "EVENT",
            ),
        )

    async def list_active(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaNotificationItem, ...]:
        return self.entries()

    async def list_conflicts(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaConflictView, ...]:
        first, second = self.entries()
        return (AgendaConflictView(first, second),)

    async def get_items(self, entry_ids: tuple[UUID, ...]) -> tuple[AgendaNotificationItem, ...]:
        values = {value.agenda_entry_id: value for value in self.entries()}
        return tuple(values[value] for value in entry_ids if value in values)


@dataclass
class Connections:
    connection_id: UUID = field(default_factory=uuid4)
    active: bool = True

    async def list_reauth_required(self, user_id: str) -> tuple[ReauthReminderCandidate, ...]:
        if not self.active:
            return ()
        return (ReauthReminderCandidate(self.connection_id, "QQ_MAIL", "Work Mail", 2, NOW),)

    async def is_reauth_episode(self, user_id: str, connection_id: UUID, reauth_epoch: int) -> bool:
        return self.active and connection_id == self.connection_id and reauth_epoch == 2


@dataclass
class Repository:
    values: dict[str, NotificationIntent] = field(default_factory=dict)
    open_subjects: set[str] = field(default_factory=set)

    async def add_or_get(self, draft: NotificationIntentDraft, now: datetime) -> NotificationIntent:
        self.values.setdefault(draft.idempotency_key, NotificationIntent.create(draft, now))
        self.open_subjects.add(draft.subject_key)
        return self.values[draft.idempotency_key]

    async def has_open(self, subject_key: str) -> bool:
        return subject_key in self.open_subjects

    async def has_recent_sent(self, subject_key: str, since: datetime) -> bool:
        return False

    async def lease_due(
        self,
        now: datetime,
        owner: str,
        duration: timedelta,
        limit: int,
    ) -> tuple[NotificationIntent, ...]:
        return ()

    async def save(self, intent: NotificationIntent, expected_version: int) -> None:
        return None

    async def recover_expired(self, now: datetime, limit: int) -> int:
        return 0


@pytest.mark.asyncio
async def test_planning_is_deterministic_and_version_keyed() -> None:
    repository = Repository()
    agenda = Agenda()
    service = NotificationPlanningService(repository, Preferences(), agenda, Connections())
    assert await service.plan("owner", NOW) == 3
    assert await service.plan("owner", NOW) == 2
    assert len(repository.values) == 3
    assert any(key.startswith("daily-digest:owner:2026-08-15") for key in repository.values)
    assert any("agenda-conflict" in key for key in repository.values)
    assert any("reauth:" in key for key in repository.values)

    agenda.version = 2
    await service.plan("owner", NOW)
    assert len(repository.values) == 4
