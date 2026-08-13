import logging

from qq_time_agent.bootstrap.logging import (
    REDACTED,
    RedactingFormatter,
    SecretRedactionFilter,
    sanitize,
)


def test_sanitize_redacts_nested_sensitive_fields_and_bearer_values() -> None:
    value = {
        "connection_id": "safe-id",
        "refresh_token": "should-not-appear",
        "headers": {"Authorization": "Bearer abc.def"},
    }
    sanitized = sanitize(value)
    assert sanitized == {
        "connection_id": "safe-id",
        "refresh_token": REDACTED,
        "headers": {"Authorization": REDACTED},
    }


def test_filter_redacts_mapping_arguments() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "credentials=%s",
        ({"client_secret": "not-for-logs"},),
        None,
    )
    assert SecretRedactionFilter().filter(record)
    assert "not-for-logs" not in str(record.args)


def test_exception_formatter_redacts_key_value_secrets() -> None:
    formatter = RedactingFormatter()
    error = RuntimeError("password='not-for-logs'")
    rendered = formatter.formatException((RuntimeError, error, None))
    assert "not-for-logs" not in rendered


def test_sanitize_redacts_oauth_callback_query_values() -> None:
    callback = "/oauth/microsoft/callback?code=not-for-logs&state=not-for-logs&safe=ok"
    sanitized = sanitize(callback)
    assert sanitized == (f"/oauth/microsoft/callback?code={REDACTED}&state={REDACTED}&safe=ok")
