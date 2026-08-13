"""Provider-local RFC email mapping without leaking provider DTOs."""

import hashlib
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from qq_time_agent.modules.inbox.contracts import MailAddress


def parse_headers(
    raw: bytes, fallback_time: datetime
) -> tuple[str, str | None, str | None, MailAddress, tuple[MailAddress, ...], datetime]:
    message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
    subject = str(message.get("Subject", ""))[:998]
    message_id = _optional(message.get("Message-ID"))
    references = str(message.get("References", "")).split()
    parent = _optional(message.get("In-Reply-To"))
    root = references[0] if references else parent or message_id
    thread_id = _digest(root) if root else None
    senders = _addresses(message.get_all("From", []))
    recipients = _addresses(message.get_all("To", []) + message.get_all("Cc", []))
    occurred_at = _date(message, fallback_time)
    return (
        subject,
        message_id,
        thread_id,
        senders[0] if senders else MailAddress(""),
        recipients,
        occurred_at,
    )


def decode_part(raw: bytes, content_type: str, charset: str | None, encoding: str) -> str:
    safe_charset = charset or "utf-8"
    prefix = (
        f'Content-Type: {content_type}; charset="{safe_charset}"\r\n'
        f"Content-Transfer-Encoding: {encoding}\r\nMIME-Version: 1.0\r\n\r\n"
    ).encode("ascii", "replace")
    try:
        parsed = BytesParser(policy=policy.default).parsebytes(prefix + raw)
        content = parsed.get_content() if isinstance(parsed, EmailMessage) else ""
        return content if isinstance(content, str) else content.decode(safe_charset, "replace")
    except (LookupError, UnicodeError, ValueError):
        return raw.decode(safe_charset, "replace")


def dedupe_key(message_id: str | None, header: bytes, body: str) -> str:
    basis = message_id.strip().lower().encode() if message_id else header + body.encode()
    prefix = "message-id" if message_id else "fingerprint"
    return f"{prefix}:{hashlib.sha256(basis).hexdigest()}"


def _addresses(values: list[object]) -> tuple[MailAddress, ...]:
    pairs = getaddresses([str(value) for value in values])
    return tuple(
        MailAddress(address.strip().lower(), name or None) for name, address in pairs if address
    )


def _date(message: EmailMessage, fallback: datetime) -> datetime:
    try:
        value = parsedate_to_datetime(str(message.get("Date", "")))
    except (TypeError, ValueError, OverflowError):
        value = fallback
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _optional(value: object | None) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _digest(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()
