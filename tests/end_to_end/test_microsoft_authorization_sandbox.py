from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from qq_time_agent.adapters.outbound.microsoft_graph.connection import (
    MicrosoftGraphConnectionAdapter,
)
from qq_time_agent.bootstrap.settings import load_runtime_config

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]


@dataclass
class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 13, tzinfo=UTC)


async def test_live_microsoft_authorization_metadata_pkce_nonce_and_scopes() -> None:
    adapter = MicrosoftGraphConnectionAdapter(load_runtime_config().microsoft, FixedClock())
    try:
        authorization = await adapter.begin_authorization("synthetic-state")
    finally:
        await adapter.close()
    parameters = parse_qs(urlparse(authorization.authorization_url).query)
    scopes = set(parameters["scope"][0].split())
    assert {
        "openid",
        "profile",
        "offline_access",
        "email",
        "User.Read",
        "Mail.Read",
    }.issubset(scopes)
    assert parameters["state"] == ["synthetic-state"]
    assert parameters["code_challenge_method"] == ["S256"]
    assert parameters["nonce"]
