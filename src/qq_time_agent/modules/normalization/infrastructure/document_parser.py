"""Bounded deterministic parsers for calendar, PDF, image, and text assets."""

import asyncio
import io
import math
import multiprocessing
import threading
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Protocol, cast

import pymupdf
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from rapidocr import RapidOCR

from qq_time_agent.modules.normalization.contracts import (
    AssetParseError,
    CalendarParseResult,
    CalendarParserPort,
    NormalizableAssetKind,
    ParsedAssetContent,
)

PARSER_VERSION = "asset-parser-pypdf6-pymupdf1-rapidocr3-v1"


class OcrResult(Protocol):
    txts: tuple[str, ...] | None


class OcrEngine(Protocol):
    def __call__(self, content: bytes) -> OcrResult: ...


class DocumentAssetParser:
    def __init__(
        self,
        calendar: CalendarParserPort,
        max_pdf_pages: int,
        max_image_pixels: int,
        max_output_chars: int,
        timeout_seconds: int,
        ocr_factory: Callable[[], OcrEngine] | None = None,
    ) -> None:
        if min(max_pdf_pages, max_image_pixels, max_output_chars, timeout_seconds) < 1:
            raise ValueError("asset parser limits must be positive")
        self._calendar = calendar
        self._max_pdf_pages = max_pdf_pages
        self._max_image_pixels = max_image_pixels
        self._max_output_chars = max_output_chars
        self._timeout = timeout_seconds
        self._ocr_factory = ocr_factory or _rapid_ocr
        self._ocr: OcrEngine | None = None
        self._ocr_lock = threading.Lock()

    async def parse(
        self, content: bytes, kind: NormalizableAssetKind, owner_timezone: str
    ) -> ParsedAssetContent:
        if kind in {NormalizableAssetKind.ICS, NormalizableAssetKind.TEXT}:
            return self._parse_safe(content, kind, owner_timezone)
        return await asyncio.to_thread(
            _parse_in_process,
            content,
            kind,
            owner_timezone,
            self._max_pdf_pages,
            self._max_image_pixels,
            self._max_output_chars,
            self._timeout,
            self._ocr_factory,
        )

    def _parse_safe(
        self, content: bytes, kind: NormalizableAssetKind, owner_timezone: str
    ) -> ParsedAssetContent:
        try:
            return self._parse_sync(content, kind, owner_timezone)
        except AssetParseError:
            raise
        except (ValueError, TypeError, OSError, UnidentifiedImageError) as exc:
            raise AssetParseError("MalformedAsset") from exc

    def _parse_sync(
        self, content: bytes, kind: NormalizableAssetKind, owner_timezone: str
    ) -> ParsedAssetContent:
        if kind is NormalizableAssetKind.ICS:
            calendar = self._calendar.parse(content, owner_timezone)
            return ParsedAssetContent(
                _calendar_text(calendar, self._max_output_chars), PARSER_VERSION, calendar
            )
        if kind is NormalizableAssetKind.PDF:
            return self._pdf(content)
        if kind is NormalizableAssetKind.IMAGE:
            return self._image(content)
        text = content.decode("utf-8")
        return ParsedAssetContent(_bounded(text, self._max_output_chars), PARSER_VERSION)

    def _pdf(self, content: bytes) -> ParsedAssetContent:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise AssetParseError("EncryptedPdfUnsupported")
        if not reader.pages or len(reader.pages) > self._max_pdf_pages:
            raise AssetParseError("PdfPageLimit")
        document = pymupdf.open(  # type: ignore[no-untyped-call]
            stream=content, filetype="pdf"
        )
        try:
            chunks: list[str] = []
            used_ocr = False
            for index, page in enumerate(reader.pages):
                extracted = (page.extract_text() or "").strip()
                if len(extracted) >= 20:
                    chunks.append(extracted)
                    continue
                used_ocr = True
                chunks.append(self._ocr_page(document[index]))
            text = _bounded_join(chunks, self._max_output_chars)
            return ParsedAssetContent(
                text, PARSER_VERSION, page_count=len(reader.pages), used_ocr=used_ocr
            )
        finally:
            document.close()  # type: ignore[no-untyped-call]

    def _image(self, content: bytes) -> ParsedAssetContent:
        with Image.open(io.BytesIO(content)) as image:
            pixels = image.width * image.height
            if pixels < 1 or pixels > self._max_image_pixels:
                raise AssetParseError("ImagePixelLimit")
            image.load()
            output = io.BytesIO()
            image.convert("RGB").save(output, format="PNG")
        text = self._recognize(output.getvalue())
        return ParsedAssetContent(
            _bounded(text, self._max_output_chars), PARSER_VERSION, used_ocr=True
        )

    def _ocr_page(self, page: pymupdf.Page) -> str:
        base_pixels = page.rect.width * page.rect.height
        scale = min(2.0, 0.98 * math.sqrt(self._max_image_pixels / max(base_pixels, 1.0)))
        if scale <= 0:
            raise AssetParseError("ImagePixelLimit")
        matrix = pymupdf.Matrix(scale, scale)  # type: ignore[no-untyped-call]
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        if pixmap.width * pixmap.height > self._max_image_pixels:
            raise AssetParseError("ImagePixelLimit")
        return self._recognize(
            pixmap.tobytes("png")  # type: ignore[no-untyped-call]
        )

    def _recognize(self, content: bytes) -> str:
        with self._ocr_lock:
            if self._ocr is None:
                self._ocr = self._ocr_factory()
        result = self._ocr(content)
        return "\n".join(result.txts or ())


def _parse_in_process(
    content: bytes,
    kind: NormalizableAssetKind,
    owner_timezone: str,
    max_pdf_pages: int,
    max_image_pixels: int,
    max_output_chars: int,
    timeout_seconds: int,
    ocr_factory: Callable[[], OcrEngine],
) -> ParsedAssetContent:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_parse_process_target,
        args=(
            send,
            content,
            kind,
            owner_timezone,
            max_pdf_pages,
            max_image_pixels,
            max_output_chars,
            ocr_factory,
        ),
        daemon=True,
    )
    process.start()
    send.close()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join()
        receive.close()
        raise AssetParseError("AssetProcessingTimeout")
    try:
        if not receive.poll(1):
            raise AssetParseError("AssetProcessingFailed")
        status, payload = receive.recv()
    finally:
        receive.close()
        process.close()
    if status == "ok" and isinstance(payload, ParsedAssetContent):
        return payload
    if status == "asset-error" and isinstance(payload, str):
        raise AssetParseError(payload)
    if status == "malformed":
        raise AssetParseError("MalformedAsset")
    raise AssetParseError("AssetProcessingFailed")


def _parse_process_target(
    send: Connection,
    content: bytes,
    kind: NormalizableAssetKind,
    owner_timezone: str,
    max_pdf_pages: int,
    max_image_pixels: int,
    max_output_chars: int,
    ocr_factory: Callable[[], OcrEngine],
) -> None:
    try:
        parser = DocumentAssetParser(
            calendar=_calendar_parser(),
            max_pdf_pages=max_pdf_pages,
            max_image_pixels=max_image_pixels,
            max_output_chars=max_output_chars,
            timeout_seconds=1,
            ocr_factory=ocr_factory,
        )
        send.send(("ok", parser._parse_sync(content, kind, owner_timezone)))
    except AssetParseError as exc:
        send.send(("asset-error", exc.failure_class))
    except (ValueError, TypeError, OSError, UnidentifiedImageError):
        send.send(("malformed", None))
    except Exception:
        send.send(("failed", None))
    finally:
        send.close()


def _calendar_parser() -> CalendarParserPort:
    from qq_time_agent.modules.normalization.infrastructure.icalendar_parser import IcalendarParser

    return IcalendarParser()


def _rapid_ocr() -> OcrEngine:
    return cast("OcrEngine", RapidOCR())


def _calendar_text(value: CalendarParseResult, maximum: int) -> str:
    chunks = [f"METHOD: {value.method}"]
    for event in value.events:
        chunks.extend(
            (
                f"UID: {event.uid}",
                f"SEQUENCE: {event.sequence}",
                f"CHANGE: {event.change_kind.value}",
                f"STATUS: {event.status}",
                f"TITLE: {event.title}",
                f"START: {event.starts_at.isoformat() if event.starts_at else ''}",
                f"END: {event.ends_at.isoformat() if event.ends_at else ''}",
                f"LOCATION: {event.location or ''}",
                f"RRULE: {event.recurrence_rule or ''}",
            )
        )
    return _bounded_join(chunks, maximum)


def _bounded_join(chunks: list[str], maximum: int) -> str:
    return _bounded("\n".join(value.strip() for value in chunks if value.strip()), maximum)


def _bounded(value: str, maximum: int) -> str:
    normalized = value.replace("\x00", "").strip()
    if not normalized:
        raise AssetParseError("AssetContainsNoText")
    if len(normalized) > maximum:
        raise AssetParseError("AssetOutputTooLarge")
    return normalized
