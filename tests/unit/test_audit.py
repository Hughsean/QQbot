from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from qq_time_agent.modules.audit.application.service import AuditService
from qq_time_agent.modules.audit.contracts import AuditEvent


@dataclass
class Repository:
    values: list[AuditEvent] = field(default_factory=list)

    async def add(self, event: AuditEvent) -> None:
        self.values.append(event)


@pytest.mark.asyncio
async def test_audit_accepts_minimized_append_only_event() -> None:
    repository = Repository()
    event = AuditEvent(
        "source-deleted",
        "owner",
        "mail:1",
        "SUCCEEDED",
        datetime(2026, 8, 20, tzinfo=UTC),
        {"tombstone_id": "synthetic"},
    )
    await AuditService(repository).append(event)
    assert repository.values == [event]


@pytest.mark.asyncio
async def test_audit_rejects_content_secrets_naive_time_and_invalid_references() -> None:
    service = AuditService(Repository())
    now = datetime(2026, 8, 20, tzinfo=UTC)
    with pytest.raises(ValueError, match="privacy"):
        await service.append(AuditEvent("event", "owner", "mail:1", "OK", now, {"token": "no"}))
    with pytest.raises(ValueError, match="timezone-aware"):
        await service.append(
            AuditEvent("event", "owner", "mail:1", "OK", datetime(2026, 8, 20), {})
        )
    with pytest.raises(ValueError, match="references"):
        await service.append(AuditEvent(" ", "owner", "mail:1", "OK", now, {}))
