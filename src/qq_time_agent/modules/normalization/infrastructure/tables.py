"""SQLAlchemy table exclusively owned by Normalization."""

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class NormalizationBase(DeclarativeBase):
    pass


class NormalizedContentRow(NormalizationBase):
    __tablename__ = "normalization_contents"

    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512), index=True)


class NormalizedAssetRow(NormalizationBase):
    __tablename__ = "normalization_assets"

    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    inbox_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(120), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512), index=True)
    calendar_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
