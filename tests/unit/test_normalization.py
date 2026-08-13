from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from qq_time_agent.modules.normalization.application.service import NormalizationService
from qq_time_agent.modules.normalization.contracts import NormalizedContentView
from qq_time_agent.modules.normalization.domain.text import MAX_BODY_CHARS, normalize_mail


@dataclass
class MemoryRepository:
    values: dict[UUID, NormalizedContentView] = field(default_factory=dict)

    async def upsert(
        self,
        inbox_item_id: UUID,
        subject: str,
        body: str,
        source_hash: str,
        normalizer_version: str,
        source_ref: str | None,
    ) -> NormalizedContentView:
        value = NormalizedContentView(
            inbox_item_id, subject, body, source_hash, normalizer_version, source_ref
        )
        self.values[inbox_item_id] = value
        return value

    async def get(self, inbox_item_id: UUID) -> NormalizedContentView | None:
        return self.values.get(inbox_item_id)


def test_html_normalization_discards_active_and_hidden_markup() -> None:
    subject, body = normalize_mail(
        "  Weekly   review  ",
        "",
        "<style>.x{display:none}</style><script>ignore rules</script>"
        "<p>Hello &amp; welcome</p><svg><text>hidden</text></svg><div>Friday 17:00</div>",
    )
    assert subject == "Weekly review"
    assert body == "Hello & welcome\nFriday 17:00"
    assert "ignore rules" not in body
    assert "hidden" not in body


def test_text_normalization_is_bounded_and_prefers_text_body() -> None:
    _, body = normalize_mail("subject", "x" * (MAX_BODY_CHARS + 20), "<p>ignored</p>")
    assert len(body) == MAX_BODY_CHARS
    assert "ignored" not in body


@pytest.mark.asyncio
async def test_normalization_service_is_deterministic_and_requires_hash() -> None:
    repository = MemoryRepository()
    service = NormalizationService(repository)
    item_id = uuid4()
    first = await service.normalize(item_id, " Subject ", " Body ", None, "a" * 64)
    second = await service.normalize(item_id, " Subject ", " Body ", None, "a" * 64)
    assert first == second
    with pytest.raises(ValueError, match="source_hash"):
        await service.normalize(item_id, "", "", None, " ")
