"""PostgreSQL source asset repository with parent deletion fencing."""

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.contracts.source import SourceType, TrustLevel
from qq_time_agent.modules.inbox.application.asset_ports import SourceAssetContext
from qq_time_agent.modules.inbox.application.source_refs import build_source_ref
from qq_time_agent.modules.inbox.domain.assets import (
    AssetFetchStatus,
    AssetKind,
    AssetParseStatus,
    SourceAsset,
)
from qq_time_agent.modules.inbox.infrastructure.tables import InboxItemRow, InboxSourceAssetRow


class StaleAssetVersionError(RuntimeError):
    pass


class InboxParentUnavailableError(RuntimeError):
    pass


class SqlSourceAssetRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add_or_get(self, asset: SourceAsset) -> SourceAsset:
        async with self._sessions.begin() as session:
            parent = await session.scalar(
                select(InboxItemRow)
                .where(InboxItemRow.inbox_item_id == asset.inbox_item_id)
                .with_for_update()
            )
            if parent is None or parent.deleted_at is not None:
                raise InboxParentUnavailableError("asset parent is missing or deleted")
            await session.execute(
                insert(InboxSourceAssetRow)
                .values(**_asset_values(asset))
                .on_conflict_do_nothing(constraint="uq_inbox_assets_parent_provider")
            )
            row = await session.scalar(
                select(InboxSourceAssetRow).where(
                    InboxSourceAssetRow.inbox_item_id == asset.inbox_item_id,
                    InboxSourceAssetRow.provider_asset_id == asset.provider_asset_id,
                )
            )
            if row is None:
                raise RuntimeError("source asset could not be persisted")
            return _to_asset(row)

    async def get(self, asset_id: UUID) -> SourceAsset | None:
        async with self._sessions() as session:
            row = await session.get(InboxSourceAssetRow, asset_id)
            return None if row is None else _to_asset(row)

    async def get_context(self, asset_id: UUID) -> SourceAssetContext | None:
        async with self._sessions() as session:
            row = await session.get(InboxSourceAssetRow, asset_id)
            if row is None:
                return None
            parent = await session.get(InboxItemRow, row.inbox_item_id)
            if parent is None:
                return None
            return SourceAssetContext(
                _to_asset(row),
                parent.connection_id,
                parent.external_id,
                SourceType(parent.source_type),
                build_source_ref(
                    SourceType(parent.source_type), parent.connection_id, parent.external_id
                ),
            )

    async def save(self, asset: SourceAsset, expected_version: int) -> None:
        values = _asset_values(asset)
        values.pop("asset_id")
        values.pop("inbox_item_id")
        values.pop("provider_asset_id")
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(InboxSourceAssetRow)
                .where(
                    InboxSourceAssetRow.asset_id == asset.asset_id,
                    InboxSourceAssetRow.version == expected_version,
                )
                .values(**values)
            )
            if cast("CursorResult[tuple[()]]", result).rowcount != 1:
                raise StaleAssetVersionError("source asset was modified concurrently")

    async def list_expired(self, now: datetime, limit: int) -> tuple[SourceAsset, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("expiry time must be timezone-aware")
        if limit <= 0 or limit > 1000:
            raise ValueError("asset expiry limit must be between 1 and 1000")
        async with self._sessions() as session:
            rows = await session.scalars(
                select(InboxSourceAssetRow)
                .where(
                    InboxSourceAssetRow.purge_at <= now,
                    InboxSourceAssetRow.deleted_at.is_(None),
                )
                .order_by(InboxSourceAssetRow.purge_at, InboxSourceAssetRow.asset_id)
                .limit(limit)
            )
            return tuple(_to_asset(row) for row in rows)

    async def list_pending(self, limit: int) -> tuple[SourceAsset, ...]:
        if limit <= 0 or limit > 1000:
            raise ValueError("asset pending limit must be between 1 and 1000")
        async with self._sessions() as session:
            rows = await session.scalars(
                select(InboxSourceAssetRow)
                .where(
                    InboxSourceAssetRow.fetch_status == AssetFetchStatus.DISCOVERED.value,
                    InboxSourceAssetRow.deleted_at.is_(None),
                )
                .order_by(InboxSourceAssetRow.created_at, InboxSourceAssetRow.asset_id)
                .limit(limit)
            )
            return tuple(_to_asset(row) for row in rows)


def _asset_values(asset: SourceAsset) -> dict[str, object]:
    return {
        "asset_id": asset.asset_id,
        "inbox_item_id": asset.inbox_item_id,
        "provider_asset_id": asset.provider_asset_id,
        "provider_locator": asset.provider_locator,
        "kind": asset.kind.value,
        "filename": asset.filename,
        "declared_content_type": asset.declared_content_type,
        "detected_content_type": asset.detected_content_type,
        "declared_size": asset.declared_size,
        "transfer_encoding": asset.transfer_encoding,
        "actual_size": asset.actual_size,
        "content_sha256": asset.content_sha256,
        "storage_key": asset.storage_key,
        "trust_level": asset.trust_level.value,
        "fetch_status": asset.fetch_status.value,
        "parse_status": asset.parse_status.value,
        "parser_version": asset.parser_version,
        "failure_class": asset.failure_class,
        "purge_at": asset.purge_at,
        "created_at": asset.created_at,
        "fetched_at": asset.fetched_at,
        "parsed_at": asset.parsed_at,
        "deleted_at": asset.deleted_at,
        "version": asset.version,
    }


def _to_asset(row: InboxSourceAssetRow) -> SourceAsset:
    return SourceAsset(
        asset_id=row.asset_id,
        inbox_item_id=row.inbox_item_id,
        provider_asset_id=row.provider_asset_id,
        provider_locator=row.provider_locator,
        kind=AssetKind(row.kind),
        filename=row.filename,
        declared_content_type=row.declared_content_type,
        declared_size=row.declared_size,
        transfer_encoding=row.transfer_encoding,
        trust_level=TrustLevel(row.trust_level),
        purge_at=row.purge_at,
        created_at=row.created_at,
        fetch_status=AssetFetchStatus(row.fetch_status),
        parse_status=AssetParseStatus(row.parse_status),
        detected_content_type=row.detected_content_type,
        actual_size=row.actual_size,
        content_sha256=row.content_sha256,
        storage_key=row.storage_key,
        parser_version=row.parser_version,
        failure_class=row.failure_class,
        fetched_at=row.fetched_at,
        parsed_at=row.parsed_at,
        deleted_at=row.deleted_at,
        version=row.version,
    )
