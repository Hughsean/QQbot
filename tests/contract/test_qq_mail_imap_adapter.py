from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from qq_time_agent.adapters.outbound.qq_mail.cursor import ImapCursor
from qq_time_agent.adapters.outbound.qq_mail.imap import QqMailImapAdapter
from qq_time_agent.bootstrap.config_models import QqMailConfig
from qq_time_agent.modules.credentials.contracts import CredentialHandle, CredentialKind
from qq_time_agent.modules.inbox.contracts import MailChange, MailProvider, MailProviderError


@dataclass
class Clock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


HEADER = (
    b"From: =?utf-8?b?5rWL6K+V?= <sender@example.com>\r\n"
    b"To: Owner <owner@qq.com>\r\nSubject: =?utf-8?b?5pel56iL?=\r\n"
    b"Date: Wed, 12 Aug 2026 09:00:00 +0800\r\n"
    b"Message-ID: <stable@example.com>\r\n\r\n"
)
STRUCTURE = (
    b'1 (BODY[HEADER] {200} BODYSTRUCTURE (("TEXT" "PLAIN" ("CHARSET" "UTF-8") '
    b'NIL NIL "BASE64" 16 1 NIL NIL NIL NIL)("APPLICATION" "PDF" ("NAME" "report.pdf") '
    b'NIL NIL "BASE64" 999 NIL ("ATTACHMENT" ("FILENAME" "report.pdf")) NIL NIL) '
    b'"MIXED" ("BOUNDARY" "x") NIL NIL NIL) RFC822.SIZE 1200)'
)


@dataclass
class Session:
    uidvalidity: int = 101
    search_result: bytes = b"7"
    transient_searches: int = 0
    commands: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    login_values: list[str] = field(default_factory=list)
    structure: bytes = STRUCTURE
    header: bytes = HEADER
    body: bytes = b"5pel56iL5a6J5o6S"

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        self.login_values.append(password)
        return "OK", [b"authenticated"]

    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> tuple[str, list[bytes]]:
        assert mailbox == "INBOX" and readonly
        return "OK", [b"1"]

    def response(self, code: str) -> tuple[str, list[bytes] | None]:
        return code, [str(self.uidvalidity).encode()]

    def uid(self, command: str, *args: object) -> tuple[str, list[object]]:
        self.commands.append((command, args))
        if command == "search":
            if self.transient_searches:
                self.transient_searches -= 1
                raise OSError("synthetic network interruption")
            return "OK", [self.search_result]
        query = str(args[-1])
        if "BODY.PEEK[HEADER]" in query:
            return "OK", [(self.structure, self.header), b")"]
        if "BODY.PEEK[" in query:
            return "OK", [(b"1 (BODY[part] {16}", self.body), b")"]
        raise AssertionError(f"unexpected IMAP fetch: {query}")

    def logout(self) -> tuple[str, list[bytes]]:
        return "BYE", [b"closed"]


def adapter(session: Session, retries: int = 0) -> QqMailImapAdapter:
    config = QqMailConfig("imap.qq.com", 993, 10, retries, 50)
    return QqMailImapAdapter(config, Clock(), lambda context, timeout: session)


@pytest.mark.asyncio
async def test_adapter_maps_unified_model_and_never_fetches_attachment() -> None:
    session = Session()
    value = adapter(session)
    provider: MailProvider = value
    credential = CredentialHandle("not-for-logs-code", CredentialKind.IMAP_AUTH_CODE, None)

    page = await provider.fetch_page(
        credential, "owner@qq.com", None, datetime(2026, 8, 1, tzinfo=UTC)
    )
    complete = await provider.fetch_content(credential, "owner@qq.com", page.changes[0])

    assert page.round_complete and ImapCursor.decode(page.continuation_url) == ImapCursor(101, 7)
    assert complete.subject == "日程"
    assert complete.body == "日程安排"
    assert complete.attachments[0].filename == "report.pdf"
    queries = [str(args[-1]) for command, args in session.commands if command == "fetch"]
    assert any("BODY.PEEK[1]" in query for query in queries)
    assert all("BODY.PEEK[2]" not in query for query in queries)
    assert all("BODY.PEEK[]" not in query and "RFC822.PEEK" not in query for query in queries)


@pytest.mark.asyncio
async def test_cursor_advances_and_uidvalidity_change_rescans_safely() -> None:
    session = Session(search_result=b"8 9")
    value = adapter(session)
    credential = CredentialHandle("synthetic-code", CredentialKind.IMAP_AUTH_CODE, None)
    since = datetime(2026, 8, 1, tzinfo=UTC)

    await value.fetch_page(credential, "owner@qq.com", ImapCursor(101, 7).encode(), since)
    session.uidvalidity = 202
    await value.fetch_page(credential, "owner@qq.com", ImapCursor(101, 9).encode(), since)

    searches = [args for command, args in session.commands if command == "search"]
    assert searches[0] == (None, "UID", "8:*")
    assert searches[1][1] == "SINCE"


@pytest.mark.asyncio
async def test_transient_failure_retries_only_within_bound() -> None:
    first = Session(transient_searches=1)
    second = Session()
    sessions = iter((first, second))
    config = QqMailConfig("imap.qq.com", 993, 10, 1, 50)
    value = QqMailImapAdapter(
        config,
        Clock(),
        lambda context, timeout: next(sessions),
        sleep=lambda delay: _no_sleep(delay),
        jitter=lambda: 0,
    )
    credential = CredentialHandle("synthetic-code", CredentialKind.IMAP_AUTH_CODE, None)
    page = await value.fetch_page(
        credential, "owner@qq.com", None, datetime(2026, 8, 1, tzinfo=UTC)
    )
    assert page.round_complete


async def _no_sleep(delay: float) -> None:
    assert delay == 1


@pytest.mark.asyncio
async def test_provider_errors_and_repr_never_contain_authorization_code() -> None:
    class AuthenticationSession(Session):
        def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
            return "NO", [b"failed"]

    value = adapter(AuthenticationSession())
    code = "not-for-logs-private-authorization-code"
    with pytest.raises(MailProviderError) as captured:
        await value.verify("owner@qq.com", SecretStr(code))
    assert code not in repr(value)
    assert code not in repr(captured.value)


@pytest.mark.asyncio
async def test_external_identifier_is_stable_and_mailbox_scoped() -> None:
    session = Session()
    value = adapter(session)
    credential = CredentialHandle("synthetic-code", CredentialKind.IMAP_AUTH_CODE, None)
    first = await value.fetch_page(
        credential, "owner@qq.com", None, datetime(2026, 8, 1, tzinfo=UTC)
    )
    second = await value.fetch_page(
        credential, "owner@qq.com", None, datetime(2026, 8, 1, tzinfo=UTC)
    )
    assert first.changes[0].external_id == second.changes[0].external_id
    assert "owner@qq.com" not in first.changes[0].external_id
    assert not isinstance(first.changes[0], (bytes, dict))
    assert isinstance(first.changes[0], MailChange)


@pytest.mark.asyncio
async def test_singlepart_plain_text_and_html_body_are_mapped() -> None:
    plain = Session(
        structure=(
            b'1 (BODY[HEADER] {200} BODYSTRUCTURE ("TEXT" "PLAIN" '
            b'("CHARSET" "UTF-8") NIL NIL "QUOTED-PRINTABLE" 12 1 NIL NIL NIL NIL))'
        ),
        body=b"plain=20body",
    )
    html = Session(
        structure=(
            b'1 (BODY[HEADER] {200} BODYSTRUCTURE (("TEXT" "HTML" '
            b'("CHARSET" "UTF-8") NIL NIL "7BIT" 18 1 NIL NIL NIL NIL) '
            b'"ALTERNATIVE" ("BOUNDARY" "x") NIL NIL NIL))'
        ),
        body=b"<p>safe html</p>",
    )
    credential = CredentialHandle("synthetic-code", CredentialKind.IMAP_AUTH_CODE, None)
    since = datetime(2026, 8, 1, tzinfo=UTC)

    plain_page = await adapter(plain).fetch_page(credential, "owner@qq.com", None, since)
    plain_content = await adapter(plain).fetch_content(
        credential, "owner@qq.com", plain_page.changes[0]
    )
    html_page = await adapter(html).fetch_page(credential, "owner@qq.com", None, since)
    html_content = await adapter(html).fetch_content(
        credential, "owner@qq.com", html_page.changes[0]
    )

    assert plain_content.body == "plain body"
    assert plain_content.body_content_type == "text/plain"
    assert html_content.body == "<p>safe html</p>"
    assert html_content.body_content_type == "text/html"
