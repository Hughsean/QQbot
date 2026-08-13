"""Official QQ SDK containment, owner gate, and reconnect supervision."""

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Protocol

import botpy  # type: ignore[import-untyped]
from botpy import Intents
from botpy.message import C2CMessage  # type: ignore[import-untyped]

from qq_time_agent.bootstrap.config_models import OwnerConfig, QqConfig
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.source import (
    IngressType,
    QqIngressPort,
    SourceEnvelope,
    SourceSender,
    SourceType,
    TrustLevel,
)

LOGGER = logging.getLogger(__name__)


class GatewayClient(Protocol):
    async def start(self, app_id: str, secret: str) -> None: ...

    async def close(self) -> None: ...

    async def send_active(self, openid: str, content: str) -> str: ...

    async def wait_ready(self, timeout_seconds: float) -> None: ...


class OfficialQqGateway:
    def __init__(
        self,
        qq: QqConfig,
        owner: OwnerConfig,
        ingress: QqIngressPort,
        clock: Clock,
        client_factory: Callable[["QqMessageProcessor"], GatewayClient] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._qq = qq
        self._processor = QqMessageProcessor(owner, ingress, clock)
        self._client_factory = client_factory or (
            lambda processor: _BotpyClient(processor, qq.sandbox)
        )
        self._sleep = sleep
        self._client: GatewayClient | None = None

    async def run_forever(self) -> None:
        failures = 0
        while True:
            client = self._client_factory(self._processor)
            self._client = client
            try:
                await client.start(
                    self._qq.app_id.get_secret_value(), self._qq.secret.get_secret_value()
                )
                failures = 0
            except asyncio.CancelledError:
                await client.close()
                raise
            except Exception:
                failures += 1
                LOGGER.exception("QQ gateway disconnected", extra={"attempt": failures})
            await self._sleep(min(60.0, float(2 ** min(failures, 6))))

    async def send_active(self, content: str) -> str:
        if self._client is None:
            raise RuntimeError("QQ gateway is not connected")
        return await self._client.send_active(
            self._processor.owner_openid.get_secret_value(), content
        )

    async def wait_ready(self, timeout_seconds: float = 30.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while self._client is None:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("QQ gateway client was not created")
            await self._sleep(0.01)
        remaining = max(0.01, deadline - asyncio.get_running_loop().time())
        await self._client.wait_ready(remaining)


class QqMessageProcessor:
    def __init__(self, owner: OwnerConfig, ingress: QqIngressPort, clock: Clock) -> None:
        self.owner_openid = owner.qq_openid
        self._ingress = ingress
        self._clock = clock

    async def process(
        self,
        author_openid: str,
        message_id: str,
        content: str,
        occurred_at: datetime,
    ) -> str | None:
        if not secrets.compare_digest(author_openid, self.owner_openid.get_secret_value()):
            return None
        envelope = SourceEnvelope(
            source_type=SourceType.QQ_DIRECT,
            ingress_type=IngressType.DIRECT,
            external_id=message_id,
            thread_id=None,
            occurred_at=_require_aware(occurred_at),
            received_at=_require_aware(self._clock.now()),
            sender=SourceSender(author_openid),
            content_ref=f"qq:{message_id}",
            content_hash=f"sha256:{hashlib.sha256(content.encode()).hexdigest()}",
            trust_level=TrustLevel.T1,
            metadata={"message_kind": "c2c"},
        )
        try:
            return await self._ingress.receive(envelope, content)
        except (LookupError, PermissionError, ValueError) as exc:
            return f"无法执行: {exc}"
        except Exception as exc:
            LOGGER.exception(
                "QQ command processing failed",
                extra={"failure_class": type(exc).__name__},
            )
            return "处理失败, 请稍后重试。"


class _BotpyClient(botpy.Client):  # type: ignore[misc]
    def __init__(self, processor: QqMessageProcessor, sandbox: bool) -> None:
        super().__init__(
            intents=Intents(public_messages=True),
            timeout=10,
            is_sandbox=sandbox,
            bot_log=False,
        )
        self._processor = processor
        self._ready = asyncio.Event()

    async def on_ready(self) -> None:
        self._ready.set()

    async def on_c2c_message_create(self, message: C2CMessage) -> None:
        reply = await self._processor.process(
            str(message.author.user_openid),
            str(message.id),
            str(message.content),
            _parse_timestamp(str(message.timestamp)),
        )
        if reply is not None:
            await message.reply(content=reply)

    async def start(self, app_id: str, secret: str) -> None:
        await super().start(app_id, secret)

    async def send_active(self, openid: str, content: str) -> str:
        result = await self.api.post_c2c_message(openid=openid, content=content)
        return _delivery_id(result)

    async def wait_ready(self, timeout_seconds: float) -> None:
        await asyncio.wait_for(self._ready.wait(), timeout_seconds)


def _delivery_id(result: object) -> str:
    if isinstance(result, Mapping):
        for field in ("id", "msg_id", "message_id"):
            value = result.get(field)
            if value:
                return str(value)
        raise RuntimeError("QQ response omitted delivery identifier")
    identifier = getattr(result, "id", None)
    if not identifier:
        raise RuntimeError("QQ response omitted delivery identifier")
    return str(identifier)


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("QQ timestamp is not RFC3339") from exc


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value
