from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaDraft
from qq_time_agent.modules.agenda.domain.models import AgendaEntry


def _draft() -> AgendaDraft:
    start = datetime(2026, 8, 20, tzinfo=UTC)
    return AgendaDraft(
        "EVENT", "评审", start, start + timedelta(hours=1), "UTC", ("source",), uuid4()
    )


def test_agenda_draft_and_mutation_invariants() -> None:
    draft = _draft()
    for invalid in (
        replace(draft, kind="NOTE"),
        replace(draft, timezone="Invalid/Zone"),
        replace(draft, title=""),
        replace(draft, starts_at=datetime(2026, 8, 20)),
        replace(draft, ends_at=draft.starts_at),
    ):
        with pytest.raises(ValueError):
            AgendaEntry.create(uuid4(), invalid)
    entry = AgendaEntry.create(uuid4(), draft)
    revised = replace(draft, title="新评审")
    entry.revise(uuid4(), 1, revised)
    assert entry.draft.title == "新评审" and entry.version == 2
    entry.cancel(uuid4(), 2)
    with pytest.raises(ValueError, match="not active"):
        entry.complete(3)
