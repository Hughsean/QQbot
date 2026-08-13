"""Private append-only Audit persistence port."""

from typing import Protocol

from qq_time_agent.modules.audit.contracts import AuditEvent


class AuditRepository(Protocol):
    async def add(self, event: AuditEvent) -> None: ...
