"""Provider-neutral notification actions and interaction contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class NotificationAction:
    action_type: str
    label: str
    value: str | None = None
    token: str | None = None


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    content: str
    actions: tuple[NotificationAction, ...] = ()


@dataclass(frozen=True, slots=True)
class ReminderActionToken:
    token_hash: str
    owner_id: str
    reminder_id: UUID
    agenda_entry_id: UUID
    agenda_entry_version: int
    occurrence: int
    action_type: str
    action_value: str | None
    expires_at: datetime
    used_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReminderActionResult:
    message: str
    idempotent: bool = False


class ReminderActionTokenPort(Protocol):
    async def issue(
        self,
        *,
        owner_id: str,
        reminder_id: UUID,
        agenda_entry_id: UUID,
        agenda_entry_version: int,
        occurrence: int,
        action_type: str,
        action_value: str | None,
        expires_at: datetime,
    ) -> str: ...

    async def consume(
        self, token: str, owner_id: str, now: datetime
    ) -> ReminderActionToken | None: ...


class ReminderActionHandler(Protocol):
    async def handle(self, action: ReminderActionToken) -> ReminderActionResult: ...


class InteractionDispatcher(Protocol):
    async def dispatch(
        self,
        interaction_id: str,
        owner_id: str,
        button_id: str,
        button_data: str,
    ) -> ReminderActionResult: ...
