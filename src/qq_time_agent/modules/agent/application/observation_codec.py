"""Canonical JSON encoding for persisted Agent tool observations."""

import json
from collections.abc import Mapping

from qq_time_agent.modules.agent.contracts.models import ToolObservation

_FORMAT = "agent-observation-v2"


class ObservationEncodingError(ValueError):
    """A tool returned a value outside the JSON observation contract."""


def canonicalize_observation_output(value: object, maximum_chars: int) -> str:
    """Return bounded, deterministic JSON text without producing invalid fragments."""

    if maximum_chars < 1:
        raise ValueError("Observation character limit must be positive")
    try:
        normalized = _normalize(value)
        encoded = _dump(normalized)
    except (ObservationEncodingError, TypeError, ValueError) as exc:
        encoded = _dump(
            {
                "error": "unsupported_tool_observation",
                "value_type": type(value).__name__,
            }
        )
        if len(encoded) > maximum_chars:
            raise ObservationEncodingError("Observation limit cannot hold an error value") from exc
        return encoded
    if len(encoded) <= maximum_chars:
        return encoded
    if isinstance(normalized, str):
        return _bounded_string(normalized, maximum_chars)
    replacement = _dump(
        {
            "error": "tool_observation_too_large",
            "encoded_chars": len(encoded),
        }
    )
    if len(replacement) > maximum_chars:
        raise ObservationEncodingError("Observation limit cannot hold a bounded value")
    return replacement


def serialize_observation(value: ToolObservation) -> dict[str, object]:
    """Encode a new observation using the versioned canonical storage shape."""

    output = value.output
    if not isinstance(output, str):
        raise ObservationEncodingError("ToolObservation output must be canonical JSON text")
    json.loads(output)
    return {
        "format": _FORMAT,
        "call_id": value.call_id,
        "name": value.name,
        "output_json": output,
        "is_error": value.is_error,
        "arguments_hash": value.arguments_hash,
    }


def deserialize_observation(value: Mapping[str, object]) -> ToolObservation | None:
    """Read canonical observations and opaque legacy string observations."""

    call_id = value.get("call_id")
    name = value.get("name")
    is_error = value.get("is_error")
    arguments_hash = value.get("arguments_hash")
    if not (
        isinstance(call_id, str)
        and call_id
        and isinstance(name, str)
        and name
        and isinstance(is_error, bool)
        and isinstance(arguments_hash, str)
    ):
        return None
    format_name = value.get("format")
    if format_name is None:
        output = value.get("output")
        if not isinstance(output, str):
            return None
        return ToolObservation(call_id, name, output, is_error, arguments_hash)
    if format_name != _FORMAT:
        return None
    output_json = value.get("output_json")
    if not isinstance(output_json, str):
        return None
    try:
        json.loads(output_json)
    except json.JSONDecodeError:
        return None
    return ToolObservation(call_id, name, output_json, is_error, arguments_hash)


def observation_token_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return canonicalize_observation_output(value, 1_000_000)


def _normalize(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ObservationEncodingError("Non-finite numbers are not valid JSON")
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ObservationEncodingError("Observation object keys must be strings")
            result[key] = _normalize(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    raise ObservationEncodingError("Tool observation is not JSON-compatible")


def _dump(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _bounded_string(value: str, maximum_chars: int) -> str:
    low = 0
    high = len(value)
    best = _dump("")
    while low <= high:
        middle = (low + high) // 2
        candidate = _dump(value[:middle])
        if len(candidate) <= maximum_chars:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    if len(best) > maximum_chars:
        raise ObservationEncodingError("Observation limit cannot hold a JSON string")
    return best
