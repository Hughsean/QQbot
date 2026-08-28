"""Official QQ SDK containment, owner gate, and reconnect supervision."""

import asyncio
import hashlib
import logging
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Protocol

import botpy  # type: ignore[import-untyped]
from botpy import Intents
from botpy.message import C2CMessage  # type: ignore[import-untyped]

from qq_time_agent.bootstrap.config_models import OwnerConfig, QqConfig
from qq_time_agent.contracts.clock import Clock
from qq_time_agent.contracts.message_presentation import format_direct_reply
from qq_time_agent.contracts.source import (
    IngressType,
    QqAssetIngressPort,
    QqIngressPort,
    SourceAssetDescriptor,
    SourceEnvelope,
    SourceSender,
    SourceType,
    TrustLevel,
)
from qq_time_agent.modules.agent.contracts import AgentResponseProtocolError
from qq_time_agent.modules.notifications.contracts import NotificationPreSendTransientError

LOGGER = logging.getLogger(__name__)

_DIAGNOSTIC_MAX_DEPTH = 5
_DIAGNOSTIC_MAX_ENTRIES = 120
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_SAFE_MIME_TYPE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
_SAFE_ATTACHMENT_NUMBERS = frozenset({"size", "width", "height"})


def _summarize_raw_event(payload: object) -> dict[str, object]:  # noqa: C901
    """Summarize raw QQ event shape without retaining scalar values."""

    event = payload.get("d", {}) if isinstance(payload, Mapping) else {}
    summary: dict[str, object] = {"event_type": type(event).__name__}
    fields: list[str] = []
    attachments: list[dict[str, object]] = []

    def visit(value: object, path: str, depth: int) -> None:  # noqa: C901
        if len(fields) >= _DIAGNOSTIC_MAX_ENTRIES or depth > _DIAGNOSTIC_MAX_DEPTH:
            return
        if isinstance(value, Mapping):
            if path.startswith("attachments["):
                metadata: dict[str, object] = {
                    "fields": sorted(
                        str(k) if _SAFE_FIELD_NAME.fullmatch(str(k)) else "<redacted-field>"
                        for k in value
                    )
                }
                mime = value.get("content_type")
                if isinstance(mime, str) and _SAFE_MIME_TYPE.fullmatch(mime.lower()):
                    metadata["mime_type"] = mime.lower()
                for number_name in _SAFE_ATTACHMENT_NUMBERS:
                    number = value.get(number_name)
                    if (
                        isinstance(number, int)
                        and not isinstance(number, bool)
                        and 0 <= number <= 50_000_000
                    ):
                        metadata[number_name] = number
                attachments.append(metadata)
            for key, nested in value.items():
                raw_name = str(key)
                name = raw_name if _SAFE_FIELD_NAME.fullmatch(raw_name) else "<redacted-field>"
                field_path = f"{path}.{name}" if path else name
                fields.append(f"{field_path}:{type(nested).__name__}")
                if depth < _DIAGNOSTIC_MAX_DEPTH:
                    visit(nested, field_path, depth + 1)
        elif isinstance(value, (list, tuple)):
            fields.append(f"{path}:list[{len(value)}]")
            for index, nested in enumerate(value[:20]):
                visit(nested, f"{path}[{index}]", depth + 1)

    visit(event, "", 0)
    summary["fields"] = tuple(fields)
    summary["attachments"] = tuple(attachments)
    return summary


def _log_raw_event_diagnostic(payload: object) -> None:
    try:
        summary = _summarize_raw_event(payload)
        LOGGER.info(
            "QQ 网关原始事件结构诊断\N{FULLWIDTH COLON}只记录字段名、类型、附件元数据"
            "\N{FULLWIDTH COMMA}脱敏并且不记录聊天正文",
            extra={"event_structure": summary},
        )
    except Exception:
        LOGGER.warning(
            "QQ 网关原始事件结构诊断不可用",
            extra={"failure_class": "DiagnosticSummaryError"},
        )


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
        ingress: QqIngressPort | QqAssetIngressPort,
        clock: Clock,
        client_factory: Callable[["QqMessageProcessor"], GatewayClient] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._qq = qq
        self._processor = QqMessageProcessor(owner, ingress, clock, qq.display_name)
        self._client_factory = client_factory or (
            lambda processor: _BotpyClient(processor, qq.sandbox, qq.diagnostic_raw_event_once)
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
            raise NotificationPreSendTransientError("QQ gateway is not connected")
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
    def __init__(
        self,
        owner: OwnerConfig,
        ingress: QqIngressPort | QqAssetIngressPort,
        clock: Clock,
        display_name: str = "小智",
    ) -> None:
        self.owner_openid = owner.qq_openid
        self._ingress = ingress
        self._clock = clock
        self._display_name = display_name

    def is_owner(self, author_openid: str) -> bool:
        return secrets.compare_digest(author_openid, self.owner_openid.get_secret_value())

    async def process(
        self,
        author_openid: str,
        message_id: str,
        content: str,
        occurred_at: datetime,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> str | None:
        if not self.is_owner(author_openid):
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
            if assets:
                if not isinstance(self._ingress, QqAssetIngressPort):
                    return self._direct_reply("当前接入未启用图片处理能力。")
                return await self._ingress.receive(envelope, content, assets)
            return await self._ingress.receive(envelope, content)
        except AgentResponseProtocolError:
            LOGGER.warning(
                "QQ Agent 模型响应格式异常", extra={"failure_class": "InvalidAgentResponse"}
            )
            return self._direct_reply("模型回复格式异常, 请稍后重试.")
        except (LookupError, PermissionError, ValueError) as exc:
            return self._direct_reply(f"无法执行: {exc}")
        except Exception as exc:
            LOGGER.exception(
                "QQ command processing failed",
                extra={"failure_class": type(exc).__name__},
            )
            return self._direct_reply("处理失败, 请稍后重试。")

    def _direct_reply(self, content: str) -> str:
        return format_direct_reply(self._display_name, content)


class _BotpyClient(botpy.Client):  # type: ignore[misc]
    def __init__(
        self,
        processor: QqMessageProcessor,
        sandbox: bool,
        diagnostic_raw_event_once: bool = False,
    ) -> None:
        super().__init__(
            intents=Intents(public_messages=True),
            timeout=10,
            is_sandbox=sandbox,
            bot_log=False,
        )
        self._processor = processor
        self._ready = asyncio.Event()
        self._diagnostic_raw_event_once = diagnostic_raw_event_once

    async def _bot_login(self, token: Any) -> None:
        await super()._bot_login(token)
        if not self._diagnostic_raw_event_once:
            return
        connection = getattr(self, "_connection", None)
        parsers = getattr(connection, "parser", None)
        if not isinstance(parsers, dict):
            LOGGER.warning(
                "QQ 网关原始事件结构诊断不可用",
                extra={"failure_class": "DiagnosticParserUnavailable"},
            )
            self._diagnostic_raw_event_once = False
            return
        original = parsers.get("c2c_message_create")
        if not callable(original):
            LOGGER.warning(
                "QQ 网关原始事件结构诊断不可用",
                extra={"failure_class": "DiagnosticParserUnavailable"},
            )
            self._diagnostic_raw_event_once = False
            return

        def parser(payload: object) -> object:
            if self._diagnostic_raw_event_once:
                self._diagnostic_raw_event_once = False
                _log_raw_event_diagnostic(payload)
            return original(payload)

        parsers["c2c_message_create"] = parser

    async def on_ready(self) -> None:
        self._ready.set()

    async def on_c2c_message_create(self, message: C2CMessage) -> None:
        author_openid = str(message.author.user_openid)
        if not self._processor.is_owner(author_openid):
            return
        assets, unsupported = _qq_assets(getattr(message, "attachments", None))
        content = str(message.content or "")
        if unsupported and not assets and not content.strip():
            await message.reply(
                content=self._processor._direct_reply(
                    "当前官方 QQ 接口未提供此附件类型或合并转发的读取权限。"
                )
            )
            return
        reply = await self._processor.process(
            author_openid,
            str(message.id),
            content,
            _parse_timestamp(str(message.timestamp)),
            assets,
        )
        if reply is not None:
            if unsupported:
                reply = f"{reply}\n部分附件因官方 QQ 接口未提供读取能力而未处理。"
            await message.reply(content=reply)

    async def start(self, app_id: str, secret: str) -> None:
        await super().start(app_id, secret)

    async def send_active(self, openid: str, content: str) -> str:
        result = await self.api.post_c2c_message(openid=openid, content=content)
        return _delivery_id(result)

    async def wait_ready(self, timeout_seconds: float) -> None:
        await asyncio.wait_for(self._ready.wait(), timeout_seconds)


def _qq_assets(  # noqa: C901
    values: object,
) -> tuple[tuple[SourceAssetDescriptor, ...], bool]:
    if values is None:
        return (), False
    if not isinstance(values, (list, tuple)):
        return (), True
    descriptors: list[SourceAssetDescriptor] = []
    unsupported = False
    for value in values:
        locator = getattr(value, "url", None)
        content_type = getattr(value, "content_type", None)
        provider_id = getattr(value, "id", None)
        filename = getattr(value, "filename", None)
        size = getattr(value, "size", None)
        if not isinstance(locator, str) or not locator:
            unsupported = True
            continue
        if content_type is None:
            content_type = "image/unknown"
        if not isinstance(content_type, str) or not content_type.lower().startswith("image/"):
            unsupported = True
            continue
        if provider_id is None:
            provider_id = hashlib.sha256(locator.encode()).hexdigest()
        if not isinstance(provider_id, str) or not provider_id:
            unsupported = True
            continue
        if filename is not None and not isinstance(filename, str):
            unsupported = True
            continue
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
            unsupported = True
            continue
        descriptors.append(
            SourceAssetDescriptor(
                provider_id,
                locator,
                filename,
                content_type,
                size,
            )
        )
    return tuple(descriptors), unsupported


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
