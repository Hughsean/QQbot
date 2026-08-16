"""Public contracts for deterministic binary asset normalization."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from qq_time_agent.modules.normalization.contracts.calendar import CalendarParseResult


class NormalizableAssetKind(StrEnum):
    IMAGE = "IMAGE"
    PDF = "PDF"
    ICS = "ICS"
    TEXT = "TEXT"


class AssetParseError(RuntimeError):
    def __init__(self, failure_class: str) -> None:
        super().__init__(failure_class)
        self.failure_class = failure_class


@dataclass(frozen=True, slots=True)
class ParsedAssetContent:
    text: str
    parser_version: str
    calendar: CalendarParseResult | None = None
    page_count: int | None = None
    used_ocr: bool = False


@dataclass(frozen=True, slots=True)
class NormalizedAssetView:
    asset_id: UUID
    inbox_item_id: UUID
    text: str
    source_hash: str
    parser_version: str
    source_ref: str | None
    calendar: CalendarParseResult | None


class AssetParserPort(Protocol):
    async def parse(
        self, content: bytes, kind: NormalizableAssetKind, owner_timezone: str
    ) -> ParsedAssetContent: ...


class AssetNormalizationPort(Protocol):
    async def store_asset(
        self,
        asset_id: UUID,
        inbox_item_id: UUID,
        text: str,
        source_hash: str,
        parser_version: str,
        source_ref: str | None,
        calendar: CalendarParseResult | None,
    ) -> NormalizedAssetView: ...


class AssetNormalizationQueryPort(Protocol):
    async def get_asset(self, asset_id: UUID) -> NormalizedAssetView | None: ...

    async def list_assets(self, inbox_item_id: UUID) -> tuple[NormalizedAssetView, ...]: ...
