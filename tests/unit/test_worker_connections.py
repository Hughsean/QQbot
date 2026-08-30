from dataclasses import dataclass
from uuid import UUID

import pytest
from pydantic import SecretStr

from qq_time_agent.bootstrap.config_models import QqMailBootstrapConfig
from qq_time_agent.bootstrap.worker_connections import bootstrap_qq_mail
from qq_time_agent.modules.connections.application.qq_mail import QqMailConnectCommand
from qq_time_agent.modules.connections.contracts import ConnectionStatusView


@dataclass
class FakeQq:
    statuses_value: tuple[ConnectionStatusView, ...] = ()
    calls: list[QqMailConnectCommand] | None = None

    async def statuses(self, user_id: str) -> tuple[ConnectionStatusView, ...]:
        assert user_id == "owner"
        return self.statuses_value

    async def connect(self, command: QqMailConnectCommand) -> ConnectionStatusView:
        assert self.calls is not None
        self.calls.append(command)
        return ConnectionStatusView(UUID(int=1), "QQ_MAIL", "ACTIVE", (), None, None)


@pytest.mark.asyncio
async def test_bootstrap_skips_without_config() -> None:
    qq = FakeQq(calls=[])
    assert await bootstrap_qq_mail(None, qq) is False
    assert qq.calls == []


@pytest.mark.asyncio
async def test_bootstrap_skips_existing_active_connection() -> None:
    qq = FakeQq(
        (
            ConnectionStatusView(UUID(int=1), "QQ_MAIL", "ACTIVE", (), None, None),
        ),
        [],
    )
    config = QqMailBootstrapConfig(SecretStr("owner@qq.com"), SecretStr("synthetic-code"))
    assert await bootstrap_qq_mail(config, qq) is False
    assert qq.calls == []


@pytest.mark.asyncio
async def test_bootstrap_connects_once_with_secret() -> None:
    qq = FakeQq(calls=[])
    config = QqMailBootstrapConfig(SecretStr("owner@qq.com"), SecretStr("synthetic-code"))
    assert await bootstrap_qq_mail(config, qq) is True
    assert len(qq.calls or []) == 1
    assert qq.calls[0].authorization_code.get_secret_value() == "synthetic-code"
    assert "synthetic-code" not in repr(qq.calls[0])
