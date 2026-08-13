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
    access_token: CredentialHandle


class ConnectionSyncPort(Protocol):
    async def acquire_mail_access(self, connection_id: UUID) -> MailAccessGrant: ...

    async def mark_sync_succeeded(self, connection_id: UUID, completed_at: datetime) -> None: ...

    async def mark_sync_reauth_required(self, connection_id: UUID) -> None: ...
