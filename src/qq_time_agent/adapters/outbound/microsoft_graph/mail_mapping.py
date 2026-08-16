"""Microsoft Graph mail DTO to provider-neutral contract mapping."""

from datetime import UTC, datetime

from qq_time_agent.modules.inbox.contracts import (
    MailAddress,
    MailAttachmentMetadata,
    MailChange,
)


def map_change(value: object) -> MailChange:
    if not isinstance(value, dict):
        raise TypeError
    external_id = required_string(value, "id")
    if "@removed" in value:
        return MailChange(
            external_id,
            None,
            None,
            MailAddress("removed"),
            (),
            "",
            "",
            "text",
            datetime.min.replace(tzinfo=UTC),
            None,
            False,
            True,
        )
    recipients_raw = value.get("toRecipients", [])
    if not isinstance(recipients_raw, list):
        raise TypeError
    return MailChange(
        external_id,
        optional_string(value, "conversationId"),
        optional_string(value, "internetMessageId"),
        _address(value.get("sender")),
        tuple(_address(item) for item in recipients_raw),
        optional_string(value, "subject") or "",
        "",
        "text",
        _parse_datetime(required_string(value, "receivedDateTime")),
        optional_string(value, "changeKey"),
        bool(value.get("hasAttachments", False)),
    )


def map_attachment(value: object) -> MailAttachmentMetadata:
    if not isinstance(value, dict):
        raise TypeError
    attachment_id = required_string(value, "id")
    size = value.get("size")
    if size is not None and (not isinstance(size, int) or size < 0):
        raise TypeError
    return MailAttachmentMetadata(
        optional_string(value, "name"),
        optional_string(value, "contentType") or "application/octet-stream",
        size,
        attachment_id,
        attachment_id,
    )


def required_string(value: dict[object, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Graph field {key} is required")
    return result


def optional_string(value: dict[object, object], key: str) -> str | None:
    result = value.get(key)
    return result if isinstance(result, str) else None


def _address(value: object) -> MailAddress:
    if not isinstance(value, dict) or not isinstance(value.get("emailAddress"), dict):
        raise TypeError
    email = value["emailAddress"]
    return MailAddress(required_string(email, "address"), optional_string(email, "name"))


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return parsed
