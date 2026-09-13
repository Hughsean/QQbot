"""Public minimal connection capability for mail synchronization."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.credentials.contracts import CredentialHandle


@dataclass(frozen=True, slots=True)
class MailAccessGrant:
    connection_id: UUID
    user_id: str
    account_id: str
    mail_credential: CredentialHandle


@dataclass(frozen=True, slots=True)
class TaskAccessGrant:
    connection_id: UUID
    user_id: str
    account_id: str
    task_credential: CredentialHandle


class ConnectionUnavailableError(RuntimeError):
    pass


class TaskAccessError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


class ConnectionSyncPort(Protocol):
    async def acquire_mail_access(self, connection_id: UUID) -> MailAccessGrant: ...

    async def ensure_sync_available(self, connection_id: UUID) -> None: ...

    async def mark_sync_succeeded(self, connection_id: UUID, completed_at: datetime) -> None: ...

    async def mark_sync_reauth_required(self, connection_id: UUID) -> None: ...

    async def mark_sync_degraded(self, connection_id: UUID) -> None: ...


class TaskConnectionAccessPort(Protocol):
    async def acquire_task_access(self, user_id: str, connection_id: UUID) -> TaskAccessGrant: ...
