"""Deterministic security cleaning and source-local chunking."""

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser

CHUNKER_VERSION = "deterministic-v1"
MAX_CHARS = 800
OVERLAP_CHARS = 80


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    ordinal: int
    content: str
    content_hash: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []
        self._stack: list[tuple[str, bool]] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): (value or "").casefold() for key, value in attrs}
        normalized_tag = tag.casefold()
        hidden = normalized_tag in {"script", "style", "noscript"} or "display:none" in re.sub(
            r"\s+", "", attributes.get("style", "")
        )
        self._stack.append((normalized_tag, hidden))
        if hidden:
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        while self._stack:
            opened_tag, hidden = self._stack.pop()
            if hidden:
                self._hidden -= 1
            if opened_tag == normalized_tag:
                break

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.values.append(data)


def clean_and_chunk(content: str) -> tuple[ChunkDraft, ...]:
    cleaned = _clean(content)
    if not cleaned:
        raise ValueError("Knowledge source has no indexable text")
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + MAX_CHARS)
        if end < len(cleaned):
            boundary = max(cleaned.rfind("\n", start, end), cleaned.rfind("。", start, end))
            if boundary > start + MAX_CHARS // 2:
                end = boundary + 1
        chunks.append(cleaned[start:end].strip())
        if end == len(cleaned):
            break
        start = max(start + 1, end - OVERLAP_CHARS)
    return tuple(
        ChunkDraft(index, value, hashlib.sha256(value.encode()).hexdigest())
        for index, value in enumerate(chunks)
        if value
    )


def _clean(content: str) -> str:
    parser = _TextExtractor()
    parser.feed(content)
    text = " ".join(parser.values) if "<" in content and ">" in content else content
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"(?i)(ignore previous|system prompt|调用工具|忽略.*指令)", "[外部文本]", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
