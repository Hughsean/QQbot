"""Provider-neutral ingress envelope defined by the v1 contract."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID


class SourceType(StrEnum):
    QQ_DIRECT = "QQ_DIRECT"
    QQ_FORWARD = "QQ_FORWARD"
    OWNER_NOTE = "OWNER_NOTE"
    MICROSOFT_MAIL = "MICROSOFT_MAIL"
    QQ_MAIL = "QQ_MAIL"


class IngressType(StrEnum):
    DIRECT = "DIRECT"
    FORWARDED = "FORWARDED"
    SYNC = "SYNC"


class TrustLevel(StrEnum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


@dataclass(frozen=True, slots=True)
class SourceSender:
    provider_id: str
    display: str | None = None


@dataclass(frozen=True, slots=True)
class SourceAssetDescriptor:
    provider_asset_id: str
    provider_locator: str
    filename: str | None
    content_type: str
    declared_size: int | None
    transfer_encoding: str | None = None


@dataclass(frozen=True, slots=True)
class SourceEnvelope:
    source_type: SourceType
    ingress_type: IngressType
    external_id: str
    thread_id: str | None
    occurred_at: datetime
    received_at: datetime
    sender: SourceSender
    content_ref: str
    content_hash: str
    trust_level: TrustLevel
    metadata: dict[str, str]


class SourceAssetDiscoveryPort(Protocol):
    async def discover(
        self,
        inbox_item_id: UUID,
        attachments: tuple[SourceAssetDescriptor, ...],
        now: datetime,
    ) -> tuple[UUID, ...]: ...


class QqIngressPort(Protocol):
    async def receive(self, envelope: SourceEnvelope, content: str) -> str | None:
        """Accept an owner-authenticated direct message and optionally return a reply."""


@runtime_checkable
class QqAssetIngressPort(Protocol):
    async def receive(
        self,
        envelope: SourceEnvelope,
        content: str,
        assets: tuple[SourceAssetDescriptor, ...] = (),
    ) -> str | None: ...
