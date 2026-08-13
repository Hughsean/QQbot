"""Provider-neutral ingress envelope defined by the v1 contract."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class SourceType(StrEnum):
    QQ_DIRECT = "QQ_DIRECT"
    QQ_FORWARD = "QQ_FORWARD"
    OWNER_NOTE = "OWNER_NOTE"
    MICROSOFT_MAIL = "MICROSOFT_MAIL"


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


class QqIngressPort(Protocol):
    async def receive(self, envelope: SourceEnvelope, content: str) -> str | None:
        """Accept an owner-authenticated direct message and optionally return a reply."""
