"""Strict-TLS, read-only QQ Mail IMAP adapter."""

import asyncio
import hashlib
import imaplib
import random
import ssl
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from typing import Protocol, TypeVar, cast

from pydantic import SecretStr

from qq_time_agent.adapters.outbound.qq_mail.bodystructure import (
    BodyPart,
    body_parts,
    parse_bodystructure,
)
from qq_time_agent.adapters.outbound.qq_mail.cursor import ImapCursor
from qq_time_agent.adapters.outbound.qq_mail.mime import decode_part, dedupe_key, parse_headers
from qq_time_agent.bootstrap.config_models import QqMailConfig
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.modules.credentials.contracts import CredentialHandle
from qq_time_agent.modules.inbox.contracts import (
    MailAttachmentMetadata,
    MailChange,
    MailDeltaPage,
    MailProviderError,
)

T = TypeVar("T")


class ImapSession(Protocol):
    def login(self, user: str, password: str) -> tuple[str, list[bytes]]: ...
    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> tuple[str, list[bytes]]: ...
    def response(self, code: str) -> tuple[str, list[bytes] | None]: ...
    def uid(self, command: str, *args: object) -> tuple[str, list[object]]: ...
    def logout(self) -> tuple[str, list[bytes]]: ...


class ImapSessionFactory(Protocol):
    def __call__(self, context: ssl.SSLContext, timeout: float) -> ImapSession: ...


class QqMailImapAdapter:
    def __init__(
        self,
        config: QqMailConfig,
        clock: Clock,
        session_factory: ImapSessionFactory | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        if config.host != "imap.qq.com" or config.port != 993:
            raise ValueError("QQ Mail IMAP requires imap.qq.com:993")
        self._config = config
        self._clock = clock
        self._context = ssl.create_default_context()
        self._context.check_hostname = True
        self._context.verify_mode = ssl.CERT_REQUIRED
        self._factory = session_factory or self._new_session
        self._sleep = sleep
        self._jitter = jitter

    async def verify(self, address: str, authorization_code: SecretStr) -> None:
        secret = authorization_code.get_secret_value()
        await self._retry(lambda: self._verify_sync(address, secret))

    async def fetch_page(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        cursor: str | None,
        since: datetime,
    ) -> MailDeltaPage:
        _require_aware(since)
        secret = mail_credential.reveal(self._clock.now())
        return await self._retry(lambda: self._fetch_page_sync(account_id, secret, cursor, since))

    async def fetch_content(
        self, mail_credential: CredentialHandle, account_id: str, change: MailChange
    ) -> MailChange:
        secret = mail_credential.reveal(self._clock.now())
        return await self._retry(lambda: self._fetch_content_sync(account_id, secret, change))

    async def close(self) -> None:
        return None

    def _new_session(self, context: ssl.SSLContext, timeout: float) -> ImapSession:
        return cast(
            ImapSession,
            imaplib.IMAP4_SSL(
                self._config.host,
                self._config.port,
                ssl_context=context,
                timeout=timeout,
            ),
        )

    def _verify_sync(self, address: str, secret: str) -> None:
        session = self._login(address, secret)
        try:
            _ok(session.select("INBOX", readonly=True))
        finally:
            _logout(session)

    def _fetch_page_sync(
        self, address: str, secret: str, cursor_value: str | None, since: datetime
    ) -> MailDeltaPage:
        cursor = ImapCursor.decode(cursor_value)
        session = self._login(address, secret)
        try:
            _ok(session.select("INBOX", readonly=True))
            uidvalidity = _uidvalidity(session)
            reset = cursor is None or cursor.uidvalidity != uidvalidity
            previous_uid = 0 if cursor is None else cursor.last_uid
            search = _search_uids(session, since, None if reset else previous_uid)
            selected = search[: self._config.page_size]
            changes = tuple(
                self._metadata(session, address, uidvalidity, uid, since) for uid in selected
            )
            last_uid = selected[-1] if selected else (0 if reset else previous_uid)
            return MailDeltaPage(
                changes,
                ImapCursor(uidvalidity, last_uid).encode(),
                len(search) <= self._config.page_size,
            )
        finally:
            _logout(session)

    def _fetch_content_sync(self, address: str, secret: str, change: MailChange) -> MailChange:
        uidvalidity, uid = _parse_external_id(address, change.external_id)
        session = self._login(address, secret)
        try:
            _ok(session.select("INBOX", readonly=True))
            if _uidvalidity(session) != uidvalidity:
                raise MailProviderError("TransientProvider")
            header, parts = _fetch_structure(session, uid)
            body_part = _preferred_body(parts)
            raw_body = b"" if body_part is None else _fetch_section(session, uid, body_part.section)
            body = (
                ""
                if body_part is None
                else decode_part(
                    raw_body, body_part.content_type, body_part.charset, body_part.encoding
                )
            )
            attachments = tuple(
                MailAttachmentMetadata(part.filename, part.content_type, part.size)
                for part in parts
                if part.attachment
            )
            return replace(
                change,
                body=body,
                body_content_type=body_part.content_type if body_part else "text/plain",
                has_attachments=bool(attachments),
                dedupe_key=dedupe_key(change.internet_message_id, header, body),
                attachments=attachments,
            )
        finally:
            _logout(session)

    def _metadata(
        self, session: ImapSession, address: str, uidvalidity: int, uid: int, since: datetime
    ) -> MailChange:
        header, parts = _fetch_structure(session, uid)
        subject, message_id, thread_id, sender, recipients, occurred_at = parse_headers(
            header, since
        )
        attachments = tuple(
            MailAttachmentMetadata(part.filename, part.content_type, part.size)
            for part in parts
            if part.attachment
        )
        external_id = _external_id(address, uidvalidity, uid)
        initial_dedupe = dedupe_key(message_id, header, "") if message_id else None
        return MailChange(
            external_id,
            thread_id,
            message_id,
            sender,
            recipients,
            subject,
            "",
            "text/plain",
            occurred_at,
            str(uid),
            bool(attachments),
            dedupe_key=initial_dedupe,
            attachments=attachments,
        )

    def _login(self, address: str, secret: str) -> ImapSession:
        session = self._factory(self._context, self._config.timeout_seconds)
        try:
            _ok(session.login(address, secret), authentication=True)
        except imaplib.IMAP4.error:
            _logout(session)
            raise MailProviderError("Authentication") from None
        except Exception:
            _logout(session)
            raise
        return session

    async def _retry(self, operation: Callable[[], T]) -> T:
        attempts = self._config.max_retries + 1
        for attempt in range(attempts):
            try:
                return await asyncio.to_thread(operation)
            except MailProviderError as exc:
                if exc.failure_class != "TransientProvider" or attempt + 1 >= attempts:
                    raise
            except imaplib.IMAP4.error:
                if attempt + 1 >= attempts:
                    raise MailProviderError("TransientProvider") from None
            except (imaplib.IMAP4.abort, TimeoutError, OSError, ssl.SSLError):
                if attempt + 1 >= attempts:
                    raise MailProviderError("TransientProvider") from None
            await self._sleep(min(30.0, 2.0**attempt + self._jitter()))
        raise AssertionError("unreachable")


def _fetch_structure(session: ImapSession, uid: int) -> tuple[bytes, tuple[BodyPart, ...]]:
    status, data = session.uid("fetch", str(uid), "(BODY.PEEK[HEADER] BODYSTRUCTURE RFC822.SIZE)")
    _ok((status, []))
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


def _fetch_section(session: ImapSession, uid: int, section: str) -> bytes:
    status, data = session.uid("fetch", str(uid), f"(BODY.PEEK[{section}])")
    _ok((status, []))
    for item in data:
        if isinstance(item, tuple) and len(item) == 2:
            return bytes(item[1])
    raise MailProviderError("PermanentProvider")


def _preferred_body(parts: tuple[BodyPart, ...]) -> BodyPart | None:
    readable = [part for part in parts if not part.attachment]
    return next((part for part in readable if part.content_type == "text/plain"), None) or next(
        (part for part in readable if part.content_type == "text/html"), None
    )


def _search_uids(session: ImapSession, since: datetime, last_uid: int | None) -> list[int]:
    if last_uid is None:
        criterion: tuple[object, ...] = (None, "SINCE", since.strftime("%d-%b-%Y"))
    else:
        criterion = (None, "UID", f"{last_uid + 1}:*")
    status, data = session.uid("search", *criterion)
    _ok((status, []))
    raw = data[0] if data else b""
    if not isinstance(raw, bytes):
        raise MailProviderError("PermanentProvider")
    values = sorted({int(value) for value in raw.split() if value.isdigit()})
    return values if last_uid is None else [value for value in values if value > last_uid]


def _uidvalidity(session: ImapSession) -> int:
    status, data = session.response("UIDVALIDITY")
    if status != "UIDVALIDITY" or not data:
        raise MailProviderError("PermanentProvider")
    try:
        return int(data[0])
    except (TypeError, ValueError) as exc:
        raise MailProviderError("PermanentProvider") from exc


def _ok(response: tuple[str, list[bytes]], authentication: bool = False) -> None:
    if response[0] != "OK":
        failure = "Authentication" if authentication else "TransientProvider"
        raise MailProviderError(failure)


def _logout(session: ImapSession) -> None:
    with suppress(imaplib.IMAP4.error, OSError):
        session.logout()


def _external_id(address: str, uidvalidity: int, uid: int) -> str:
    mailbox = hashlib.sha256(address.strip().lower().encode()).hexdigest()[:20]
    return f"qq-mail:{mailbox}:INBOX:{uidvalidity}:{uid}"


def _parse_external_id(address: str, value: str) -> tuple[int, int]:
    parts = value.split(":")
    expected = hashlib.sha256(address.strip().lower().encode()).hexdigest()[:20]
    if len(parts) != 5 or parts[:3] != ["qq-mail", expected, "INBOX"]:
        raise MailProviderError("PermanentProvider")
    try:
        uidvalidity, uid = int(parts[3]), int(parts[4])
    except ValueError as exc:
        raise MailProviderError("PermanentProvider") from exc
    if uidvalidity < 1 or uid < 1:
        raise MailProviderError("PermanentProvider")
    return uidvalidity, uid


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
