from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from qq_time_agent.adapters.inbound.http.owner_session import (
    OwnerAuthenticationError,
    OwnerSessionSigner,
    verify_csrf,
)


@dataclass
class FixedClock:
    value: datetime

    def now(self) -> datetime:
        return self.value


def test_owner_session_is_signed_expiring_and_tamper_evident() -> None:
    clock = FixedClock(datetime(2026, 8, 13, tzinfo=UTC))
    signer = OwnerSessionSigner(SecretStr("k" * 32), clock)
    token = signer.issue("owner", timedelta(minutes=5))
    assert signer.verify(token).user_id == "owner"
    with pytest.raises(OwnerAuthenticationError, match="signature"):
        signer.verify(token[:-1] + ("a" if token[-1] != "a" else "b"))
    clock.value += timedelta(minutes=5)
    with pytest.raises(OwnerAuthenticationError, match="expired"):
        signer.verify(token)


def test_csrf_requires_matching_cookie_and_header() -> None:
    verify_csrf("synthetic-csrf", "synthetic-csrf")
    with pytest.raises(OwnerAuthenticationError, match="CSRF"):
        verify_csrf("synthetic-csrf", "wrong")
