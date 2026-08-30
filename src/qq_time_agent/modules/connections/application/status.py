"""Read-only, provider-scoped external connection status queries."""

import re
from dataclasses import dataclass
from enum import StrEnum

from qq_time_agent.modules.connections.application.ports import ConnectionRepository
from qq_time_agent.modules.connections.application.views import to_connection_view
from qq_time_agent.modules.connections.contracts import ConnectionStatusView
from qq_time_agent.modules.connections.domain.models import ConnectionProvider

_EMAIL_ADDRESS = re.compile(
    r"(?i)\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Z0-9-]+(?:\.[A-Z0-9-]+)+)\b"
)


class ConnectionStatusResult(StrEnum):
    OK = "OK"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AMBIGUOUS_PROVIDER = "AMBIGUOUS_PROVIDER"
    UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER"


@dataclass(frozen=True, slots=True)
class ResolvedProvider:
    phrase: str
    provider: str | None
    result: ConnectionStatusResult


@dataclass(frozen=True, slots=True)
class ConnectionStatusSnapshot:
    requested_provider: str
    provider: str | None
    result: ConnectionStatusResult
    connections: tuple[ConnectionStatusView, ...] = ()


class ConnectionStatusQueryService:
    """Query persisted connection metadata without performing a live probe."""

    def __init__(self, repository: ConnectionRepository) -> None:
        self._repository = repository

    async def query(self, user_id: str, provider_phrase: str) -> ConnectionStatusSnapshot:
        resolved = resolve_provider_phrase(provider_phrase)
        if resolved.provider is None:
            return ConnectionStatusSnapshot(resolved.phrase, None, resolved.result)
        values = await self._repository.list_for_provider(user_id, resolved.provider)
        views = tuple(to_connection_view(value) for value in values)
        result = ConnectionStatusResult.OK if views else ConnectionStatusResult.NOT_CONFIGURED
        return ConnectionStatusSnapshot(resolved.phrase, resolved.provider, result, views)


def resolve_provider_phrase(value: str) -> ResolvedProvider:
    phrase = " ".join(value.strip().split())
    safe_phrase = _redact_email_addresses(phrase)
    if not phrase:
        return ResolvedProvider(safe_phrase, None, ConnectionStatusResult.AMBIGUOUS_PROVIDER)

    folded = phrase.casefold()
    compact = re.sub(r"[\s_-]+", "", folded)
    qq_mail_mentioned = "@qq.com" in folded or "qq邮箱" in compact or "qqmail" in compact
    microsoft_mentioned = any(
        marker in compact for marker in ("outlook", "microsoft", "hotmail", "office365")
    )
    qq_alone_mentioned = re.search(r"(?<![a-z0-9])qq(?![a-z0-9])", folded) is not None
    generic_mail_mentioned = (
        compact in {"邮箱", "邮件", "email", "mail"}
        or "邮箱" in compact
        or "邮件" in compact
        or re.search(r"(?<![a-z0-9])(?:e-?mail|mail)(?![a-z0-9])", folded) is not None
    )

    if (qq_mail_mentioned and microsoft_mentioned) or (
        qq_alone_mentioned and microsoft_mentioned
    ):
        return ResolvedProvider(safe_phrase, None, ConnectionStatusResult.AMBIGUOUS_PROVIDER)
    if qq_mail_mentioned:
        return ResolvedProvider(
            safe_phrase, ConnectionProvider.QQ_MAIL.value, ConnectionStatusResult.OK
        )
    if microsoft_mentioned:
        return ResolvedProvider(
            safe_phrase, ConnectionProvider.MICROSOFT.value, ConnectionStatusResult.OK
        )
    if qq_alone_mentioned or generic_mail_mentioned:
        return ResolvedProvider(safe_phrase, None, ConnectionStatusResult.AMBIGUOUS_PROVIDER)
    return ResolvedProvider(safe_phrase, None, ConnectionStatusResult.UNKNOWN_PROVIDER)


def _redact_email_addresses(value: str) -> str:
    return _EMAIL_ADDRESS.sub(r"***@\1", value)
