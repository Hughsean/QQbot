"""Source asset identity and lifecycle rules owned by Inbox."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from qq_time_agent.contracts.source import TrustLevel


class AssetKind(StrEnum):
    IMAGE = "IMAGE"
    PDF = "PDF"
    ICS = "ICS"
    TEXT = "TEXT"
    FILE = "FILE"
    QQ_FORWARD_BUNDLE = "QQ_FORWARD_BUNDLE"


class AssetFetchStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    STORED = "STORED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    DELETED = "DELETED"


class AssetParseStatus(StrEnum):
    PENDING = "PENDING"
    PARSED = "PARSED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"
    DELETED = "DELETED"


@dataclass(slots=True)
class SourceAsset:
    asset_id: UUID
    inbox_item_id: UUID
    provider_asset_id: str
    provider_locator: str
    kind: AssetKind
    filename: str | None
    declared_content_type: str
    declared_size: int | None
    transfer_encoding: str | None
    trust_level: TrustLevel
    purge_at: datetime
    created_at: datetime
    fetch_status: AssetFetchStatus = AssetFetchStatus.DISCOVERED
    parse_status: AssetParseStatus = AssetParseStatus.PENDING
    detected_content_type: str | None = None
    actual_size: int | None = None
    content_sha256: str | None = None
    storage_key: str | None = None
    parser_version: str | None = None
    failure_class: str | None = None
    fetched_at: datetime | None = None
    parsed_at: datetime | None = None
    deleted_at: datetime | None = None
    version: int = 1

    @classmethod
    def discover(
        cls,
        inbox_item_id: UUID,
        provider_asset_id: str,
        provider_locator: str,
        kind: AssetKind,
        declared_content_type: str,
        now: datetime,
        purge_at: datetime,
        *,
        filename: str | None = None,
        declared_size: int | None = None,
        transfer_encoding: str | None = None,
    ) -> "SourceAsset":
        _require_aware(now)
        _require_aware(purge_at)
        _require_bounded(provider_asset_id, "provider asset id", 512)
        _require_bounded(provider_locator, "provider locator", 512)
        _require_bounded(declared_content_type, "content type", 255)
        if filename is not None and len(filename) > 512:
            raise ValueError("asset filename is too long")
        if transfer_encoding is not None:
            _require_bounded(transfer_encoding, "transfer encoding", 40)
        if declared_size is not None and declared_size < 0:
            raise ValueError("asset declared size cannot be negative")
        if purge_at <= now:
            raise ValueError("asset purge time must be in the future")
        return cls(
            uuid4(),
            inbox_item_id,
            provider_asset_id,
            provider_locator,
            kind,
            filename,
            declared_content_type,
            declared_size,
            transfer_encoding,
            TrustLevel.T2,
            purge_at,
            now,
        )

    def mark_stored(
        self,
        *,
        detected_content_type: str,
        actual_size: int,
        content_sha256: str,
        storage_key: str,
        now: datetime,
    ) -> None:
        self._require_live(AssetFetchStatus.DISCOVERED)
        _require_aware(now)
        _require_bounded(detected_content_type, "detected content type", 255)
        _require_sha256(content_sha256)
        if actual_size < 0 or not storage_key:
            raise ValueError("stored asset metadata is invalid")
        self.detected_content_type = detected_content_type
        self.actual_size = actual_size
        self.content_sha256 = content_sha256
        self.storage_key = storage_key
        self.fetch_status = AssetFetchStatus.STORED
        self.fetched_at = now
        self.version += 1

    def mark_parsed(self, parser_version: str, now: datetime) -> None:
        self._require_live(AssetFetchStatus.STORED)
        _require_aware(now)
        _require_bounded(parser_version, "parser version", 120)
        self.parse_status = AssetParseStatus.PARSED
        self.parser_version = parser_version
        self.parsed_at = now
        self.failure_class = None
        self.version += 1

    def reject(self, failure_class: str, now: datetime) -> None:
        self._require_live(AssetFetchStatus.DISCOVERED)
        _require_aware(now)
        _require_bounded(failure_class, "failure class", 80)
        self.fetch_status = AssetFetchStatus.REJECTED
        self.parse_status = AssetParseStatus.UNSUPPORTED
        self.failure_class = failure_class
        self.parsed_at = now
        self.version += 1

    def mark_parse_failed(self, failure_class: str, now: datetime) -> None:
        self._require_live(AssetFetchStatus.STORED)
        _require_aware(now)
        _require_bounded(failure_class, "failure class", 80)
        self.parse_status = AssetParseStatus.FAILED
        self.failure_class = failure_class
        self.parsed_at = now
        self.version += 1

    def mark_deleted(self, now: datetime) -> None:
        _require_aware(now)
        if self.deleted_at is not None:
            return
        self.fetch_status = AssetFetchStatus.DELETED
        self.parse_status = AssetParseStatus.DELETED
        self.deleted_at = now
        self.storage_key = None
        self.version += 1

    def _require_live(self, expected: AssetFetchStatus) -> None:
        if self.deleted_at is not None or self.fetch_status is not expected:
            raise ValueError("asset state transition is not allowed")


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")


def _require_bounded(value: str, label: str, maximum: int) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be non-empty and bounded")


def _require_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("asset sha256 must be lowercase hexadecimal")
