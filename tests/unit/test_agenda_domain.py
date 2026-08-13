from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qq_time_agent.modules.agenda.contracts import AgendaDraft
from qq_time_agent.modules.agenda.domain.models import AgendaEntry


def _draft() -> AgendaDraft:
    return AgendaDraft(
        "EVENT",
        "方案评审",
        datetime(2026, 8, 19, 7, tzinfo=UTC),
        datetime(2026, 8, 19, 8, tzinfo=UTC),
        "Asia/Shanghai",
        ("inbox:test",),
        uuid4(),
    )


def test_agenda_entry_is_versioned_authoritative_fact() -> None:
    entry = AgendaEntry.create(uuid4(), _draft())
    assert entry.version == 1 and entry.status.value == "ACTIVE"
    assert entry.draft.kind == "EVENT"


@pytest.mark.parametrize(
    "change,message",
    [
        ({"kind": "UNKNOWN"}, "kind or timezone"),
        ({"timezone": "Mars/Olympus"}, "kind or timezone"),
        ({"title": " "}, "title and source"),
        ({"source_refs": ()}, "title and source"),
        ({"starts_at": datetime(2026, 8, 19, 7)}, "timezone-aware"),
        (
            {
                "ends_at": datetime(2026, 8, 19, 6, tzinfo=UTC),
            },
            "end must follow",
        ),
    ],
)
def test_agenda_rejects_invalid_facts(change: dict[str, object], message: str) -> None:
    values = asdict(_draft())
    values.update(change)
    with pytest.raises(ValueError, match=message):
        AgendaEntry.create(uuid4(), AgendaDraft(**values))
