"""QQ IMAP session primitives and opaque message/part locators."""

import hashlib
import imaplib
from contextlib import suppress
from datetime import datetime
from typing import Protocol

from qq_time_agent.adapters.outbound.qq_mail.bodystructure import (
    BodyPart,
    body_parts,
    parse_bodystructure,
)
from qq_time_agent.modules.inbox.contracts import MailAttachmentMetadata, MailProviderError


class ImapSession(Protocol):
    def login(self, user: str, password: str) -> tuple[str, list[bytes]]: ...

    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> tuple[str, list[bytes]]: ...

    def response(self, code: str) -> tuple[str, list[bytes] | None]: ...

    def uid(self, command: str, *args: object) -> tuple[str, list[object]]: ...

    def logout(self) -> tuple[str, list[bytes]]: ...


def attachment_metadata(
    parts: tuple[BodyPart, ...], uidvalidity: int, uid: int
) -> tuple[MailAttachmentMetadata, ...]:
    return tuple(
        MailAttachmentMetadata(
            part.filename,
            part.content_type,
            part.size,
            f"{uidvalidity}:{uid}:{part.section}",
            part.section,
            part.encoding,
        )
        for part in parts
        if part.attachment
    )


def fetch_structure(session: ImapSession, uid: int) -> tuple[bytes, tuple[BodyPart, ...]]:
    status, data = session.uid("fetch", str(uid), "(BODY.PEEK[HEADER] BODYSTRUCTURE RFC822.SIZE)")
    ok((status, []))
    header = b""
    metadata = b""
    for item in data:
        if isinstance(item, tuple) and len(item) == 2:
            metadata += bytes(item[0])
            header += bytes(item[1])
        elif isinstance(item, bytes):
            metadata += item
    if not header or b"BODYSTRUCTURE" not in metadata.upper():
        raise MailProviderError("PermanentProvider")
    try:
        parts = body_parts(parse_bodystructure(metadata))
    except ValueError as exc:
        raise MailProviderError("PermanentProvider") from exc
    return header, parts


def fetch_section(session: ImapSession, uid: int, section: str) -> bytes:
    status, data = session.uid("fetch", str(uid), f"(BODY.PEEK[{section}])")
    ok((status, []))
    for item in data:
        if isinstance(item, tuple) and len(item) == 2:
            return bytes(item[1])
    raise MailProviderError("PermanentProvider")


def preferred_body(parts: tuple[BodyPart, ...]) -> BodyPart | None:
    readable = [part for part in parts if not part.attachment]
    return next((part for part in readable if part.content_type == "text/plain"), None) or next(
        (part for part in readable if part.content_type == "text/html"), None
    )


def search_uids(session: ImapSession, since: datetime, last_uid: int | None) -> list[int]:
    criterion: tuple[object, ...] = (
        (None, "SINCE", since.strftime("%d-%b-%Y"))
        if last_uid is None
        else (None, "UID", f"{last_uid + 1}:*")
    )
    status, data = session.uid("search", *criterion)
    ok((status, []))
    raw = data[0] if data else b""
    if not isinstance(raw, bytes):
        raise MailProviderError("PermanentProvider")
    values = sorted({int(value) for value in raw.split() if value.isdigit()})
    return values if last_uid is None else [value for value in values if value > last_uid]


def uidvalidity(session: ImapSession) -> int:
    status, data = session.response("UIDVALIDITY")
    if status != "UIDVALIDITY" or not data:
        raise MailProviderError("PermanentProvider")
    try:
        return int(data[0])
    except (TypeError, ValueError) as exc:
        raise MailProviderError("PermanentProvider") from exc


def ok(response: tuple[str, list[bytes]], authentication: bool = False) -> None:
    if response[0] != "OK":
        failure = "Authentication" if authentication else "TransientProvider"
        raise MailProviderError(failure)


def logout(session: ImapSession) -> None:
    with suppress(imaplib.IMAP4.error, OSError):
        session.logout()


def external_id(address: str, uidvalidity_value: int, uid: int) -> str:
    mailbox = hashlib.sha256(address.strip().lower().encode()).hexdigest()[:20]
    return f"qq-mail:{mailbox}:INBOX:{uidvalidity_value}:{uid}"


def parse_external_id(address: str, value: str) -> tuple[int, int]:
    parts = value.split(":")
    expected = hashlib.sha256(address.strip().lower().encode()).hexdigest()[:20]
    if len(parts) != 5 or parts[:3] != ["qq-mail", expected, "INBOX"]:
        raise MailProviderError("PermanentProvider")
    try:
        uidvalidity_value, uid = int(parts[3]), int(parts[4])
    except ValueError as exc:
        raise MailProviderError("PermanentProvider") from exc
    if uidvalidity_value < 1 or uid < 1:
        raise MailProviderError("PermanentProvider")
    return uidvalidity_value, uid


def require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
