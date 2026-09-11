import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qq_time_agent.modules.agent.application.conversation_replay import (
    ConversationTimelineReplay,
    ReplayInputError,
)
from qq_time_agent.modules.agent.application.conversation_replay_input import (
    load_replay_events,
)
from qq_time_agent.modules.agent.contracts import ConversationEvent, ConversationEventView

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
FIXTURE = Path("tests/fixtures/conversation_timeline_replay.json")


@dataclass
class FixedClock:
    value: datetime = NOW

    def now(self) -> datetime:
        return self.value


@dataclass
class MemoryTimeline:
    events: dict[str, ConversationEventView] = field(default_factory=dict)
    sequences: dict[str, int] = field(default_factory=dict)

    async def append(self, event: ConversationEvent, now: datetime) -> ConversationEventView:
        del now
        existing = self.events.get(event.idempotency_key)
        if existing is not None:
            return existing
        sequence = self.sequences.get(event.user_id, 0) + 1
        self.sequences[event.user_id] = sequence
        view = ConversationEventView(
            event.event_id,
            event.scope_type,
            event.scope_id,
            event.user_id,
            sequence,
            event.event_type,
            event.role,
            event.occurred_at,
            event.occurred_at,
            event.content,
            event.content_ref,
            event.content_hash,
            event.delivery_status,
            event.run_id,
            event.inbox_item_id,
            event.notification_intent_id,
            event.idempotency_key,
            dict(event.metadata),
        )
        self.events[event.idempotency_key] = view
        return view

    async def current_sequence(self, user_id: str) -> int:
        return self.sequences.get(user_id, 0)


class FailingTimeline(MemoryTimeline):
    async def append(self, event: ConversationEvent, now: datetime) -> ConversationEventView:
        del event, now
        raise RuntimeError("database unavailable")


def _service(repository: MemoryTimeline) -> ConversationTimelineReplay:
    return ConversationTimelineReplay(repository, clock=FixedClock())


def _valid_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "user_id": "replay-u",
        "scope_type": "conversation",
        "scope_id": "00000000-0000-0000-0000-000000000001",
        "sequence": 1,
        "event_type": "USER_MESSAGE",
        "content": "safe replay content",
        "idempotency_key": "replay:test:1",
    }
    event.update(overrides)
    return event


def _write_json(path: Path, events: list[object]) -> Path:
    path.write_text(
        json.dumps({"version": 1, "redacted": True, "events": events}),
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_replay_is_idempotent_and_returns_metadata_only() -> None:
    repository = MemoryTimeline()
    service = _service(repository)

    first = await service.replay_path(FIXTURE)
    second = await service.replay_path(FIXTURE)

    assert (first.input_count, first.inserted_count, first.skipped_count) == (2, 2, 0)
    assert (second.input_count, second.inserted_count, second.skipped_count) == (2, 0, 2)
    assert first.failed_count == second.failed_count == 0
    assert first.user_hashes == second.user_hashes
    assert len(first.scope_hashes) == 1
    assert first.sequence_ranges == second.sequence_ranges
    assert all("脱敏" not in value for value in repr(first))
    assert len(repository.events) == 2


@pytest.mark.asyncio
async def test_replay_rejects_sensitive_or_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.json"
    path.write_text(
        '{"version": 1, "redacted": true, "events": [{"user_id": "replay-u", '
        '"scope_type": "conversation", '
        '"scope_id": "00000000-0000-0000-0000-000000000001", "sequence": 1, '
        '"event_type": "USER_MESSAGE", "content": "x", "idempotency_key": "k", '
        '"sender_id": "do-not-accept"}]}',
        encoding="utf-8",
    )

    with pytest.raises(ReplayInputError, match="unsupported fields"):
        await _service(MemoryTimeline()).replay_path(path)


@pytest.mark.asyncio
async def test_replay_rejects_sequence_gaps_and_role_mismatch(tmp_path: Path) -> None:
    gap = tmp_path / "gap.json"
    gap.write_text(
        '{"version": 1, "redacted": true, "events": [{"user_id": "replay-u", '
        '"scope_type": "conversation", '
        '"scope_id": "00000000-0000-0000-0000-000000000001", "sequence": 2, '
        '"event_type": "USER_MESSAGE", "role": "user", "content": "x", '
        '"idempotency_key": "k"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ReplayInputError, match="not contiguous"):
        await _service(MemoryTimeline()).replay_path(gap)

    mismatch = tmp_path / "role.json"
    mismatch.write_text(
        '{"version": 1, "redacted": true, "events": [{"user_id": "replay-u", '
        '"scope_type": "conversation", '
        '"scope_id": "00000000-0000-0000-0000-000000000001", "sequence": 1, '
        '"event_type": "USER_MESSAGE", "role": "agent", "content": "x", '
        '"idempotency_key": "k"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ReplayInputError, match="role does not match"):
        await _service(MemoryTimeline()).replay_path(mismatch)


@pytest.mark.asyncio
async def test_replay_rejects_external_content_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "hash.json"
    path.write_text(
        '{"version": 1, "redacted": true, "events": [{"user_id": "replay-u", '
        '"scope_type": "conversation", '
        '"scope_id": "00000000-0000-0000-0000-000000000001", "sequence": 1, '
        '"event_type": "USER_MESSAGE", "content": "x", "content_hash": "bad", '
        '"idempotency_key": "k"}]}',
        encoding="utf-8",
    )

    with pytest.raises(ReplayInputError, match="content hash"):
        await _service(MemoryTimeline()).replay_path(path)


@pytest.mark.asyncio
async def test_replay_accepts_redacted_csv(tmp_path: Path) -> None:
    path = tmp_path / "events.csv"
    path.write_text(
        "redacted,user_id,scope_type,scope_id,sequence,event_type,role,content,idempotency_key\n"
        "true,replay-csv-user,conversation,00000000-0000-0000-0000-000000000001,1,"
        "USER_MESSAGE,user,CSV回放消息,replay:csv:1\n",
        encoding="utf-8",
    )

    result = await _service(MemoryTimeline()).replay_path(path)

    assert (result.input_count, result.inserted_count, result.failed_count) == (1, 1, 0)


@pytest.mark.asyncio
async def test_replay_requires_redaction_declaration(tmp_path: Path) -> None:
    path = tmp_path / "not-redacted.json"
    path.write_text('{"version": 1, "events": []}', encoding="utf-8")

    with pytest.raises(ReplayInputError, match="explicitly redacted"):
        await _service(MemoryTimeline()).replay_path(path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "metadata"),
    (
        ("联系 raw@example.com", None),
        ("安全文本", {"sender_id": "raw-id"}),
        ("安全文本", {"source_type": "Bearer raw-secret-token"}),
    ),
)
async def test_replay_rejects_nested_or_textual_sensitive_data(
    tmp_path: Path, content: str, metadata: dict[str, object] | None
) -> None:
    path = tmp_path / "sensitive.json"
    event: dict[str, object] = {
        "user_id": "replay-u",
        "scope_type": "conversation",
        "scope_id": "00000000-0000-0000-0000-000000000001",
        "sequence": 1,
        "event_type": "USER_MESSAGE",
        "idempotency_key": "replay:sensitive",
        "content": content,
    }
    if metadata is not None:
        event["metadata"] = metadata
    path.write_text(
        json.dumps({"version": 1, "redacted": True, "events": [event]}, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ReplayInputError, match=r"sensitive|unsupported"):
        await _service(MemoryTimeline()).replay_path(path)


def test_replay_rejects_missing_unsupported_and_empty_inputs(tmp_path: Path) -> None:
    with pytest.raises(ReplayInputError, match="does not exist"):
        load_replay_events(tmp_path / "missing.json")

    unsupported = tmp_path / "events.txt"
    unsupported.write_text("redacted", encoding="utf-8")
    with pytest.raises(ReplayInputError, match="JSON or CSV"):
        load_replay_events(unsupported)

    empty = _write_json(tmp_path / "empty.json", [])
    with pytest.raises(ReplayInputError, match="must contain events"):
        load_replay_events(empty)


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        ("not-json", "cannot be read"),
        (json.dumps([]), "unsupported top-level"),
        (
            json.dumps({"version": 1, "redacted": True, "events": [], "raw": True}),
            "unsupported top-level",
        ),
        (
            json.dumps({"version": 1, "redacted": True, "events": ["bad"]}),
            "must be objects",
        ),
    ),
)
def test_replay_rejects_invalid_json_structures(tmp_path: Path, payload: str, message: str) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ReplayInputError, match=message):
        load_replay_events(path)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"user_id": "raw-user-id"}, "redacted identifier"),
        ({"sequence": True}, "must be positive"),
        ({"sequence": 0}, "must be positive"),
        ({"sequence": "nope"}, "must be positive"),
        ({"event_type": "INVALID"}, "event 1 is invalid"),
        ({"scope_id": "not-a-uuid"}, "event 1 is invalid"),
        ({"content": None}, "content is required"),
        ({"content_ref": 7}, "content_ref must be text"),
        ({"content_ref": "Bearer secret-token-value"}, "sensitive text"),
        ({"run_id": "not-a-uuid"}, "run_id is invalid"),
        ({"delivery_status": "UNKNOWN"}, "delivery status is invalid"),
        ({"metadata": ["not", "an", "object"]}, "must be an object"),
        ({"metadata": {"source_type": 1.5}}, "bounded scalars"),
        ({"metadata": {"source_type": ["nested"]}}, "bounded scalars"),
        ({"metadata": {"source_type": "x" * 257}}, "too long"),
        ({"occurred_at": 123}, "ISO-8601 string"),
        ({"occurred_at": "not-a-time"}, "occurred_at is invalid"),
        ({"occurred_at": "2026-09-10T12:00:00"}, "timezone-aware"),
    ),
)
def test_replay_rejects_invalid_event_values(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    path = _write_json(tmp_path / "invalid-event.json", [_valid_event(**overrides)])

    with pytest.raises(ReplayInputError, match=message):
        load_replay_events(path)


def test_replay_accepts_bounded_optional_fields(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path / "complete.json",
        [
            _valid_event(
                user_id="a" * 64,
                event_type="MAIL_NOTIFICATION",
                scope_type="owner_timeline",
                run_id="00000000-0000-0000-0000-000000000002",
                inbox_item_id="00000000-0000-0000-0000-000000000003",
                notification_intent_id="00000000-0000-0000-0000-000000000004",
                delivery_status="DELIVERED",
                content_ref="redacted:content:1",
                occurred_at="2026-09-10T12:00:00Z",
                metadata={"is_error": False, "call_id": 3, "source_type": "fixture"},
            )
        ],
    )

    event = load_replay_events(path)[0]

    assert event.occurred_at == NOW
    assert event.content_ref == "redacted:content:1"
    assert event.metadata == {"is_error": False, "call_id": 3, "source_type": "fixture"}


def test_replay_rejects_csv_without_redaction(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.csv"
    path.write_text("redacted,user_id\nfalse,replay-u\n", encoding="utf-8")

    with pytest.raises(ReplayInputError, match="explicitly redacted"):
        load_replay_events(path)


@pytest.mark.asyncio
async def test_replay_classifies_append_failures_without_exposing_content() -> None:
    repository = FailingTimeline()
    result = await ConversationTimelineReplay(
        repository, clock=FixedClock(), fail_fast=False
    ).replay_path(FIXTURE)

    assert (result.input_count, result.inserted_count, result.failed_count) == (2, 0, 2)
    assert result.sequence_ranges == ()
    assert "脱敏" not in repr(result)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await _service(repository).replay_path(FIXTURE)
