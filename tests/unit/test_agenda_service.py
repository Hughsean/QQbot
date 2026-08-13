from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.agenda.application.service import AgendaService
from qq_time_agent.modules.agenda.contracts import AgendaDraft
from qq_time_agent.modules.agenda.domain.models import AgendaEntry


@dataclass
class Repository:
    values: dict[UUID, AgendaEntry] = field(default_factory=dict)
    keys: dict[str, UUID] = field(default_factory=dict)

    async def create(self, entry: AgendaEntry, idempotency_key: str) -> AgendaEntry:
        existing = self.keys.get(idempotency_key)
        if existing is not None:
            return self.values[existing]
        self.keys[idempotency_key] = entry.agenda_entry_id
        self.values[entry.agenda_entry_id] = entry
        return entry

    async def get(self, entry_id: UUID) -> AgendaEntry | None:
        return self.values.get(entry_id)

    async def busy_between(
        self, range_start: datetime, range_end: datetime
    ) -> tuple[AgendaEntry, ...]:
        return tuple(
            value
            for value in self.values.values()
            if value.draft.starts_at < range_end and value.draft.ends_at > range_start
        )

    async def save(
        self, entry: AgendaEntry, expected_version: int, idempotency_key: str
    ) -> AgendaEntry:
        existing = self.keys.get(idempotency_key)
        if existing is not None:
            return self.values[existing]
        assert expected_version == entry.version - 1
        self.keys[idempotency_key] = entry.agenda_entry_id
        self.values[entry.agenda_entry_id] = entry
        return entry


def _draft(proposal_id: UUID) -> AgendaDraft:
    start = datetime(2026, 8, 20, 7, tzinfo=UTC)
    return AgendaDraft(
        "EVENT",
        "评审",
        start,
        start + timedelta(hours=1),
        "Asia/Shanghai",
        ("inbox:test",),
        proposal_id,
    )


@pytest.mark.asyncio
async def test_agenda_service_maps_busy_view_and_idempotent_entry() -> None:
    service = AgendaService(Repository())
    proposal_id = uuid4()
    first = await service.create_entry(uuid4(), _draft(proposal_id), "action-key")
    second = await service.create_entry(uuid4(), _draft(proposal_id), "action-key")
    assert first == second
    entry = await service.get_entry(first.agenda_entry_id)
    assert entry is not None and entry.proposal_id == proposal_id and entry.version == 1
    busy = await service.get_busy_intervals(
        entry.starts_at + timedelta(minutes=30), entry.ends_at + timedelta(hours=1)
    )
    assert len(busy) == 1 and not busy[0].movable


@pytest.mark.asyncio
async def test_agenda_service_rejects_bad_ranges_and_empty_key() -> None:
    service = AgendaService(Repository())
    now = datetime(2026, 8, 20, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone-aware"):
        await service.get_busy_intervals(datetime(2026, 8, 20), now)
    with pytest.raises(ValueError, match="ordered"):
        await service.get_busy_intervals(now, now)
    with pytest.raises(ValueError, match="idempotency"):
        await service.create_entry(uuid4(), _draft(uuid4()), " ")
    assert await service.get_entry(uuid4()) is None


@pytest.mark.asyncio
async def test_agenda_revise_cancel_complete_and_stale_versions() -> None:
    repository = Repository()
    service = AgendaService(repository)
    entry = await service.create_entry(uuid4(), _draft(uuid4()), "create")
    revised_draft = _draft(uuid4())
    revised = await service.revise_entry(uuid4(), entry.agenda_entry_id, 1, revised_draft, "revise")
    assert revised.version == 2
    with pytest.raises(ValueError, match="stale"):
        await service.complete_entry(entry.agenda_entry_id, 1, "stale")
    cancelled = await service.cancel_entry(uuid4(), entry.agenda_entry_id, 2, "cancel")
    assert cancelled.version == 3
    with pytest.raises(ValueError, match="not active"):
        await service.complete_entry(entry.agenda_entry_id, 3, "complete")

    other = await service.create_entry(uuid4(), _draft(uuid4()), "create-other")
    completed = await service.complete_entry(other.agenda_entry_id, 1, "complete-other")
    assert completed.version == 2
    with pytest.raises(LookupError, match="does not exist"):
        await service.cancel_entry(uuid4(), uuid4(), 1, "missing")
