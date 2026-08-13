"""Provider-neutral and credential-free connection views."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ConnectionStatusView:
    connection_id: UUID
    provider: str
    status: str
    capabilities: tuple[str, ...]
    account_mask: str | None
    last_synced_at: datetime | None
