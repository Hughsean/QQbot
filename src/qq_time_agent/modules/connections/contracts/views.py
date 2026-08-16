"""Provider-neutral and credential-free connection views."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReauthReminderCandidate:
    connection_id: UUID
    provider: str
    display_label: str
    reauth_epoch: int
    required_since: datetime


class ConnectionNotificationQueryPort(Protocol):
    async def list_reauth_required(self, user_id: str) -> tuple[ReauthReminderCandidate, ...]: ...

    async def is_reauth_episode(
        self, user_id: str, connection_id: UUID, reauth_epoch: int
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class ConnectionStatusView:
    connection_id: UUID
    provider: str
    status: str
    capabilities: tuple[str, ...]
    account_mask: str | None
    last_synced_at: datetime | None
    display_label: str = "Mailbox"
    is_default: bool = True
    sync_enabled: bool = True
