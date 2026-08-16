"""PostgreSQL idempotent normalized source asset repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from qq_time_agent.modules.normalization.contracts import (
    CalendarParseResult,
    NormalizedAssetView,
)
from qq_time_agent.modules.normalization.infrastructure.calendar_json import (
    calendar_from_json,
    calendar_to_json,
)
from qq_time_agent.modules.normalization.infrastructure.tables import NormalizedAssetRow


class SqlNormalizedAssetRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def store_asset(
        self,
        asset_id: UUID,
        inbox_item_id: UUID,
        text: str,
        source_hash: str,
        parser_version: str,
        source_ref: str | None,
        calendar: CalendarParseResult | None,
    ) -> NormalizedAssetView:
        _validate(text, source_hash, parser_version)
        values = {
            "asset_id": asset_id,
            "inbox_item_id": inbox_item_id,
            "text": text,
            "source_hash": source_hash,
            "parser_version": parser_version,
            "source_ref": source_ref,
            "calendar_payload": calendar_to_json(calendar),
        }
        async with self._sessions.begin() as session:
            await session.execute(
                insert(NormalizedAssetRow)
                .values(**values)
                .on_conflict_do_update(index_elements=[NormalizedAssetRow.asset_id], set_=values)
            )
        return NormalizedAssetView(
            asset_id, inbox_item_id, text, source_hash, parser_version, source_ref, calendar
        )

    async def get_asset(self, asset_id: UUID) -> NormalizedAssetView | None:
        async with self._sessions() as session:
            row = await session.get(NormalizedAssetRow, asset_id)
            if row is None:
                return None
            return _view(row)

    async def list_assets(self, inbox_item_id: UUID) -> tuple[NormalizedAssetView, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(NormalizedAssetRow)
                .where(NormalizedAssetRow.inbox_item_id == inbox_item_id)
                .order_by(NormalizedAssetRow.asset_id)
            )
            return tuple(_view(row) for row in rows)


def _view(row: NormalizedAssetRow) -> NormalizedAssetView:
    return NormalizedAssetView(
        row.asset_id,
        row.inbox_item_id,
        row.text,
        row.source_hash,
        row.parser_version,
        row.source_ref,
        calendar_from_json(row.calendar_payload),
    )


def _validate(text: str, source_hash: str, parser_version: str) -> None:
    if not text.strip() or len(text) > 200_000:
        raise ValueError("normalized asset text must be non-empty and bounded")
    if len(source_hash) != 64 or any(value not in "0123456789abcdef" for value in source_hash):
        raise ValueError("normalized asset source hash must be lowercase sha256")
    if not parser_version or len(parser_version) > 120:
        raise ValueError("normalized asset parser version must be bounded")
