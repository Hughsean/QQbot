"""Hash and validate provider-neutral Agent tool calls."""

import hashlib
import json
from collections.abc import Mapping


def arguments_hash(arguments: Mapping[str, object]) -> str:
    """Hash the JSON protocol value independently of mapping insertion order."""
    canonical = json.dumps(arguments, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_schema(schema: Mapping[str, object], arguments: Mapping[str, object]) -> None:
    if schema.get("type") != "object":
        raise ValueError("工具 schema 必须是 object")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
        raise ValueError("工具 schema required 无效")
    missing = [key for key in required if key not in arguments]
    if missing:
        raise ValueError(f"工具缺少必填参数: {', '.join(missing)}")
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError("工具 schema properties 无效")
    for key, value in arguments.items():
        rule = properties.get(key)
        if not isinstance(rule, Mapping):
            raise ValueError(f"工具参数未在 schema 中声明: {key}")
        _validate_value(key, value, rule)


def _validate_value(key: str, value: object, rule: Mapping[str, object]) -> None:
    expected = rule.get("type")
    valid = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "array": isinstance(value, (list, tuple)),
        "object": isinstance(value, Mapping),
    }
    if isinstance(expected, str) and expected in valid and not valid[expected]:
        raise ValueError(f"工具参数 {key} 类型不正确")
    minimum = rule.get("minimum")
    if (
        isinstance(minimum, (int, float))
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value < minimum
    ):
        raise ValueError(f"工具参数 {key} 小于最小值")
    enum = rule.get("enum")
    if isinstance(enum, list) and value not in enum:
        raise ValueError(f"工具参数 {key} 不在允许值范围")
