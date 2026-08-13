"""Idempotent deterministic mail normalization use case."""

from uuid import UUID

from qq_time_agent.modules.normalization.application.ports import NormalizedContentRepository
from qq_time_agent.modules.normalization.contracts import NormalizedContentView
from qq_time_agent.modules.normalization.domain.text import NORMALIZER_VERSION, normalize_mail


class NormalizationService:
    def __init__(self, repository: NormalizedContentRepository) -> None:
        self._repository = repository

    async def normalize(
        self,
        inbox_item_id: UUID,
        subject: str,
        body_text: str,
        body_html: str | None,
        source_hash: str,
        source_ref: str | None = None,
    ) -> NormalizedContentView:
        if not source_hash.strip():
            raise ValueError("source_hash is required")
        normalized_subject, normalized_body = normalize_mail(subject, body_text, body_html)
        return await self._repository.upsert(
            inbox_item_id,
            normalized_subject,
            normalized_body,
            source_hash,
            NORMALIZER_VERSION,
            source_ref,
        )
