"""Versioned domain event envelope for Transactional Outbox."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: UUID
    event_type: str
    schema_version: int
    aggregate_ref: str
    payload: dict[str, object]
    occurred_at: datetime
