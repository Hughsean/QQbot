"""Strict-TLS, read-only QQ Mail IMAP adapter."""

import asyncio
import imaplib
import random
import re
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from typing import Protocol, TypeVar, cast

from pydantic import SecretStr

from qq_time_agent.adapters.outbound.qq_mail.cursor import ImapCursor
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    ImapSession,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    attachment_metadata as _attachment_metadata,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    external_id as _external_id,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    fetch_section as _fetch_section,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    fetch_structure as _fetch_structure,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    logout as _logout,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    ok as _ok,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    parse_external_id as _parse_external_id,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    preferred_body as _preferred_body,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    require_aware as _require_aware,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    search_uids as _search_uids,
)
from qq_time_agent.adapters.outbound.qq_mail.imap_parts import (
    uidvalidity as _uidvalidity,
)
from qq_time_agent.adapters.outbound.qq_mail.mime import (
    decode_attachment,
    decode_part,
    dedupe_key,
    parse_headers,
)
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
        max_attachment_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        if config.host != "imap.qq.com" or config.port != 993:
            raise ValueError("QQ Mail IMAP requires imap.qq.com:993")
        self._config = config
        self._clock = clock
        self._context = ssl.create_default_context()
        self._context.check_hostname = True
        self._context.verify_mode = ssl.CERT_REQUIRED
        if max_attachment_bytes < 1:
            raise ValueError("attachment maximum bytes must be positive")
        self._factory = session_factory or self._new_session
        self._max_attachment_bytes = max_attachment_bytes
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

    async def fetch_attachment(
        self,
        mail_credential: CredentialHandle,
        account_id: str,
        message_external_id: str,
        attachment: MailAttachmentMetadata,
    ) -> bytes:
        secret = mail_credential.reveal(self._clock.now())
        return await self._retry(
            lambda: self._fetch_attachment_sync(account_id, secret, message_external_id, attachment)
        )

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
            attachments = _attachment_metadata(parts, uidvalidity, uid)
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

    def _fetch_attachment_sync(
        self,
        address: str,
        secret: str,
        message_external_id: str,
        attachment: MailAttachmentMetadata,
    ) -> bytes:
        uidvalidity, uid = _parse_external_id(address, message_external_id)
        section = attachment.provider_locator
        expected_id = f"{uidvalidity}:{uid}:{section}"
        if (
            re.fullmatch(r"[1-9][0-9]*(?:\.[1-9][0-9]*)*", section) is None
            or attachment.provider_asset_id != expected_id
            or (
                attachment.declared_size is not None
                and attachment.declared_size > self._max_attachment_bytes
            )
        ):
            raise MailProviderError("PermanentProvider")
        session = self._login(address, secret)
        try:
            _ok(session.select("INBOX", readonly=True))
            if _uidvalidity(session) != uidvalidity:
                raise MailProviderError("TransientProvider")
            raw = _fetch_section(session, uid, section)
            content = decode_attachment(
                raw, attachment.content_type, attachment.transfer_encoding or "7bit"
            )
            if not content or len(content) > self._max_attachment_bytes:
                raise MailProviderError("AssetTooLarge")
            return content
        finally:
            _logout(session)

    def _metadata(
        self, session: ImapSession, address: str, uidvalidity: int, uid: int, since: datetime
    ) -> MailChange:
        header, parts = _fetch_structure(session, uid)
        subject, message_id, thread_id, sender, recipients, occurred_at = parse_headers(
            header, since
        )
        attachments = _attachment_metadata(parts, uidvalidity, uid)
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
