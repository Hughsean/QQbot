"""Structured logging configuration with defense-in-depth secret redaction."""

import logging
import re
from collections.abc import Mapping
from types import TracebackType
from typing import Final, cast

SENSITIVE_FIELD: Final = re.compile(
    r"(?i)(authorization|cookie|secret|token|password|credential|code|verifier|key|"
    r"body|content|prompt|payload|response|completion)"
)
BEARER_VALUE: Final = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
JWT_VALUE: Final = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
KEY_VALUE: Final = re.compile(
    r"(?i)(password|secret|token|credential|authorization|key|body|content|prompt|payload|completion)"
    r"(['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}\]]+)"
)
SENSITIVE_QUERY: Final = re.compile(
    r"(?i)([?&](?:code|state|client_info|session_state|id_token|access_token)="
    r")([^&#\s]+)"
)
REDACTED: Final = "[REDACTED]"
SAFE_CONTEXT_FIELDS: Final = (
    "role",
    "job_id",
    "kind",
    "proposal_id",
    "reminder_id",
    "attempt",
    "failure_class",
    "count",
    "duration_ms",
    "step",
    "tool",
    "call_id",
    "status",
)


def sanitize(value: object, field_name: str | None = None) -> object:
    """Return a safe logging representation without mutating the input."""

    if field_name is not None and SENSITIVE_FIELD.search(field_name):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(key): sanitize(item, str(key)) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(sanitize(item) for item in value)
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        text = JWT_VALUE.sub(REDACTED, BEARER_VALUE.sub(REDACTED, value))
        text = SENSITIVE_QUERY.sub(rf"\1{REDACTED}", text)
        return KEY_VALUE.sub(rf"\1\2{REDACTED}", text)
    return value


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize(record.msg)
        if isinstance(record.args, Mapping):
            record.args = cast("Mapping[str, object]", sanitize(record.args))
        elif isinstance(record.args, tuple):
            record.args = tuple(sanitize(item) for item in record.args)
        return True


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        context = [
            f"{field}={sanitize(getattr(record, field), field)}"
            for field in SAFE_CONTEXT_FIELDS
            if hasattr(record, field)
        ]
        return f"{rendered} {' '.join(context)}" if context else rendered

    def formatException(
        self,
        exc_info: tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None],
    ) -> str:
        return str(sanitize(super().formatException(exc_info)))


def configure_logging(level: int = logging.INFO, role: str | None = None) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    if role is not None:
        logging.getLogger("qq_time_agent").info("process started", extra={"role": role})
