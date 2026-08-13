"""Privacy-minimized append-only audit contract."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: str
    actor_ref: str
    subject_ref: str
    outcome: str
    occurred_at: datetime
    metadata: dict[str, str]


class AuditPort(Protocol):
    async def append(self, event: AuditEvent) -> None: ...
