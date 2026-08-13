"""Privacy policy validation before append-only audit persistence."""

from qq_time_agent.modules.audit.application.ports import AuditRepository
from qq_time_agent.modules.audit.contracts import AuditEvent

FORBIDDEN_METADATA = {
    "authorization",
    "body",
    "code",
    "content",
    "cookie",
    "password",
    "prompt",
    "secret",
    "token",
}


class AuditService:
    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def append(self, event: AuditEvent) -> None:
        _validate(event)
        await self._repository.add(event)


def _validate(event: AuditEvent) -> None:
    required = (event.event_type, event.actor_ref, event.subject_ref, event.outcome)
    if any(not value.strip() for value in required):
        raise ValueError("Audit event references are required")
    if event.occurred_at.tzinfo is None or event.occurred_at.utcoffset() is None:
        raise ValueError("Audit event time must be timezone-aware")
    for key, value in event.metadata.items():
        if key.casefold() in FORBIDDEN_METADATA or not key.strip() or len(value) > 240:
            raise ValueError("Audit metadata violates privacy policy")
