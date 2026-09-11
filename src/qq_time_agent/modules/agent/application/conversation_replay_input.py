"""Strict parsing and redaction validation for local conversation replay inputs."""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid5

from qq_time_agent.modules.agent.contracts import (
    ConversationDeliveryStatus,
    ConversationEvent,
    ConversationEventType,
    ConversationScopeType,
)

_REPLAY_NAMESPACE = UUID("6de6fd7d-5dc3-4f02-a5c9-f1f0ac1d8f2d")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_TOP_LEVEL_FIELDS = frozenset({"version", "redacted", "events"})
_EVENT_FIELDS = frozenset(
    {
        "user_id",
        "scope_type",
        "scope_id",
        "sequence",
        "event_type",
        "role",
        "content",
        "content_hash",
        "idempotency_key",
        "occurred_at",
        "content_ref",
        "metadata",
        "run_id",
        "inbox_item_id",
        "notification_intent_id",
        "delivery_status",
    }
)
_METADATA_FIELDS = frozenset(
    {
        "arguments_hash",
        "call_id",
        "delivery",
        "is_error",
        "message_kind",
        "source_type",
        "tool",
    }
)
_REDACTED_USER_PREFIXES = ("integration-", "redacted-", "replay-", "test-")
_HEX_DIGEST = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)
_EMAIL_ADDRESS = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
_SECRET_TEXT = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")


class ReplayInputError(ValueError):
    """Raised when an export is not a valid redacted replay input."""


def load_replay_events(path: Path) -> tuple[ConversationEvent, ...]:
    rows = _load_rows(path)
    if not rows:
        raise ReplayInputError("replay input must contain events")
    parsed = tuple(_build_event(row, index) for index, row in enumerate(rows, start=1))
    _validate_sequences(parsed)
    return tuple(item[2] for item in sorted(parsed, key=lambda item: (item[0], item[1])))


def _load_rows(path: Path) -> tuple[dict[str, object], ...]:
    if not path.is_file():
        raise ReplayInputError("replay input file does not exist")
    if path.suffix.lower() == ".json":
        return _load_json_rows(path)
    if path.suffix.lower() == ".csv":
        return _load_csv_rows(path)
    raise ReplayInputError("replay input must be JSON or CSV")


def _load_json_rows(path: Path) -> tuple[dict[str, object], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayInputError("replay JSON cannot be read") from exc
    if not isinstance(payload, dict) or set(payload) - _TOP_LEVEL_FIELDS:
        raise ReplayInputError("replay JSON contains unsupported top-level fields")
    if (
        payload.get("version") != 1
        or payload.get("redacted") is not True
        or not isinstance(payload.get("events"), list)
    ):
        raise ReplayInputError("replay JSON must be version 1 and explicitly redacted")
    rows: list[dict[str, object]] = []
    for item in payload["events"]:
        if not isinstance(item, dict):
            raise ReplayInputError("replay events must be objects")
        rows.append({str(key): value for key, value in item.items()})
    return tuple(rows)


def _load_csv_rows(path: Path) -> tuple[dict[str, object], ...]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = tuple(dict(row) for row in csv.DictReader(handle))
    except OSError as exc:
        raise ReplayInputError("replay CSV cannot be read") from exc
    if not rows or any(str(row.pop("redacted", "")).lower() != "true" for row in rows):
        raise ReplayInputError("replay CSV rows must be explicitly redacted")
    return rows


def _build_event(row: dict[str, object], index: int) -> tuple[str, int, ConversationEvent]:
    unknown = set(row) - _EVENT_FIELDS
    if unknown:
        raise ReplayInputError(f"event {index} contains unsupported fields")
    try:
        user_id = _redacted_user_id(row)
        sequence = _positive_int(row.get("sequence"), "sequence")
        event_type = ConversationEventType(_text(row, "event_type"))
        scope_type = ConversationScopeType(_text(row, "scope_type"))
        idempotency_key = _safe_text(row, "idempotency_key")
        content = _safe_text(row, "content")
        event = _conversation_event(
            row, user_id, sequence, event_type, scope_type, idempotency_key, content
        )
        if row.get("role") and str(row["role"]) != event.role.value:
            raise ReplayInputError(f"event {index} role does not match event type")
        _validate_content_hash(row, event, index)
        return user_id, sequence, event
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ReplayInputError):
            raise
        raise ReplayInputError(f"event {index} is invalid") from exc


def _conversation_event(
    row: dict[str, object],
    user_id: str,
    sequence: int,
    event_type: ConversationEventType,
    scope_type: ConversationScopeType,
    idempotency_key: str,
    content: str,
) -> ConversationEvent:
    return ConversationEvent(
        scope_type=scope_type,
        scope_id=UUID(_text(row, "scope_id")),
        user_id=user_id,
        event_type=event_type,
        occurred_at=_occurred_at(row.get("occurred_at"), sequence),
        content=content,
        idempotency_key=idempotency_key,
        run_id=_optional_uuid(row.get("run_id"), "run_id")
        or uuid5(_REPLAY_NAMESPACE, f"run:{idempotency_key}"),
        inbox_item_id=_optional_uuid(row.get("inbox_item_id"), "inbox_item_id")
        or uuid5(_REPLAY_NAMESPACE, f"inbox:{idempotency_key}"),
        notification_intent_id=_optional_uuid(
            row.get("notification_intent_id"), "notification_intent_id"
        ),
        delivery_status=_delivery_status(row.get("delivery_status")),
        content_ref=_optional_safe_text(
            row.get("content_ref"), f"replay:{idempotency_key}", "content_ref"
        ),
        metadata=_metadata(row.get("metadata")),
    )


def _validate_content_hash(row: dict[str, object], event: ConversationEvent, index: int) -> None:
    supplied = str(row.get("content_hash") or "")
    if supplied and supplied != event.content_hash:
        raise ReplayInputError(f"event {index} content hash does not match content")


def _validate_sequences(parsed: tuple[tuple[str, int, ConversationEvent], ...]) -> None:
    by_user: dict[str, list[int]] = {}
    for user_id, sequence, _ in parsed:
        by_user.setdefault(user_id, []).append(sequence)
    for user_id, values in by_user.items():
        ordered = sorted(values)
        if ordered != list(range(1, len(ordered) + 1)):
            digest = sha256(user_id.encode("utf-8")).hexdigest()
            raise ReplayInputError("replay sequence is not contiguous for user hash " + digest)


def _text(row: dict[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ReplayInputError(f"replay field {name} is required")
    return value.strip()


def _safe_text(row: dict[str, object], name: str) -> str:
    return _reject_sensitive_text(_text(row, name), name)


def _optional_safe_text(value: object, default: str, name: str) -> str:
    if value in (None, ""):
        return default
    if not isinstance(value, str) or not value.strip():
        raise ReplayInputError(f"replay field {name} must be text")
    return _reject_sensitive_text(value.strip(), name)


def _redacted_user_id(row: dict[str, object]) -> str:
    value = _safe_text(row, "user_id")
    lowered = value.lower()
    if (
        value == "owner"
        or lowered.startswith(_REDACTED_USER_PREFIXES)
        or _HEX_DIGEST.fullmatch(value)
    ):
        return value
    raise ReplayInputError("replay user_id must be an owner alias or redacted identifier")


def _reject_sensitive_text(value: str, name: str) -> str:
    if _EMAIL_ADDRESS.search(value) or _SECRET_TEXT.search(value):
        raise ReplayInputError(f"replay field {name} contains sensitive text")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ReplayInputError(f"replay field {name} must be positive")
    try:
        result = int(value) if isinstance(value, str | int) else 0
    except ValueError as exc:
        raise ReplayInputError(f"replay field {name} must be positive") from exc
    if result < 1:
        raise ReplayInputError(f"replay field {name} must be positive")
    return result


def _optional_uuid(value: object, name: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ReplayInputError(f"replay field {name} is invalid") from exc


def _delivery_status(value: object) -> ConversationDeliveryStatus | None:
    if value in (None, ""):
        return None
    try:
        return ConversationDeliveryStatus(str(value))
    except ValueError as exc:
        raise ReplayInputError("replay delivery status is invalid") from exc


def _metadata(value: object) -> dict[str, object]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ReplayInputError("replay metadata must be an object")
    unknown = set(value) - _METADATA_FIELDS
    if unknown:
        raise ReplayInputError("replay metadata contains unsupported fields")
    return {str(key): _metadata_scalar(str(key), item) for key, item in value.items()}


def _metadata_scalar(key: str, item: object) -> object:
    invalid_number = isinstance(item, float) and not item.is_integer()
    if not isinstance(item, str | int | float | bool) or invalid_number:
        raise ReplayInputError("replay metadata values must be bounded scalars")
    if not isinstance(item, str):
        return item
    if len(item) > 256:
        raise ReplayInputError("replay metadata text is too long")
    return _reject_sensitive_text(item, f"metadata.{key}")


def _occurred_at(value: object, sequence: int) -> datetime:
    if value in (None, ""):
        return _EPOCH + timedelta(seconds=sequence)
    if not isinstance(value, str):
        raise ReplayInputError("replay occurred_at must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReplayInputError("replay occurred_at is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReplayInputError("replay occurred_at must be timezone-aware")
    return parsed
