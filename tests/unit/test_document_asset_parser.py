import io
import time
from dataclasses import dataclass
from typing import cast

import pymupdf
import pytest
from PIL import Image, ImageDraw

from qq_time_agent.modules.normalization.contracts import AssetParseError, NormalizableAssetKind
from qq_time_agent.modules.normalization.infrastructure.document_parser import DocumentAssetParser
from qq_time_agent.modules.normalization.infrastructure.icalendar_parser import IcalendarParser


@dataclass
class OcrResult:
    txts: tuple[str, ...] | None


class FixedOcr:
    def __call__(self, content: bytes) -> OcrResult:
        assert content.startswith(b"\x89PNG")
        return OcrResult(("Scanned meeting at 10:00",))


class SlowOcr:
    def __call__(self, content: bytes) -> OcrResult:
        del content
        time.sleep(10)
        return OcrResult(("too late",))


def _parser(*, pages: int = 5, pixels: int = 2_000_000) -> DocumentAssetParser:
    return DocumentAssetParser(IcalendarParser(), pages, pixels, 20_000, 10, ocr_factory=FixedOcr)


def _pdf(text: str | None, page_count: int = 1) -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        for _ in range(page_count):
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        return cast(bytes, document.tobytes())  # type: ignore[no-untyped-call]
    finally:
        document.close()  # type: ignore[no-untyped-call]


def _image(text: str, size: tuple[int, int] = (300, 80)) -> bytes:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((20, 20), text, fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_pdf_extracts_native_text_without_ocr() -> None:
    result = await _parser().parse(
        _pdf("Planning meeting Friday at 10:00 in Conference Room"),
        NormalizableAssetKind.PDF,
        "Asia/Shanghai",
    )
    assert "Planning meeting" in result.text
    assert result.page_count == 1 and not result.used_ocr


@pytest.mark.asyncio
async def test_scanned_pdf_page_uses_bounded_ocr() -> None:
    result = await _parser().parse(_pdf(None), NormalizableAssetKind.PDF, "Asia/Shanghai")
    assert result.text == "Scanned meeting at 10:00"
    assert result.used_ocr


@pytest.mark.asyncio
async def test_pdf_page_and_image_pixel_limits_are_enforced() -> None:
    with pytest.raises(AssetParseError, match="PdfPageLimit"):
        await _parser(pages=1).parse(_pdf("page", 2), NormalizableAssetKind.PDF, "Asia/Shanghai")
    with pytest.raises(AssetParseError, match="ImagePixelLimit"):
        await _parser(pixels=1_000).parse(
            _image("large", (100, 100)), NormalizableAssetKind.IMAGE, "Asia/Shanghai"
        )


@pytest.mark.asyncio
async def test_ics_uses_deterministic_calendar_parser() -> None:
    content = b"""BEGIN:VCALENDAR
VERSION:2.0
METHOD:REQUEST
BEGIN:VEVENT
UID:event-1
SEQUENCE:2
DTSTART:20260820T100000Z
DTEND:20260820T110000Z
SUMMARY:Planning
END:VEVENT
END:VCALENDAR
"""
    result = await _parser().parse(content, NormalizableAssetKind.ICS, "Asia/Shanghai")
    assert result.calendar is not None
    assert result.calendar.events[0].uid == "event-1"
    assert "SEQUENCE: 2" in result.text


@pytest.mark.asyncio
async def test_real_offline_ocr_recognizes_synthetic_image() -> None:
    parser = DocumentAssetParser(IcalendarParser(), 2, 1_000_000, 20_000, 30)
    result = await parser.parse(
        _image("Meeting 10:00"), NormalizableAssetKind.IMAGE, "Asia/Shanghai"
    )
    assert "Meeting 10:00" in result.text


@pytest.mark.asyncio
async def test_ocr_process_is_terminated_at_hard_timeout() -> None:
    parser = DocumentAssetParser(IcalendarParser(), 2, 1_000_000, 20_000, 1, ocr_factory=SlowOcr)
    started = time.monotonic()
    with pytest.raises(AssetParseError, match="AssetProcessingTimeout"):
        await parser.parse(_image("slow"), NormalizableAssetKind.IMAGE, "Asia/Shanghai")
    assert time.monotonic() - started < 4
