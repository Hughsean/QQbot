"""Pure bounded HTML/text normalization for untrusted mail content."""

import html
import re
from html.parser import HTMLParser

MAX_SUBJECT_CHARS = 2_000
MAX_BODY_CHARS = 200_000
NORMALIZER_VERSION = "mail-text-v1"


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "template", "noscript"}:
            self._ignored_depth += 1
        if self._ignored_depth == 0 and tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "template", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif self._ignored_depth == 0 and tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def normalize_mail(subject: str, body_text: str, body_html: str | None) -> tuple[str, str]:
    normalized_subject = _collapse(html.unescape(subject))[:MAX_SUBJECT_CHARS]
    body = body_text if body_text.strip() else _html_to_text(body_html or "")
    return normalized_subject, _collapse(body)[:MAX_BODY_CHARS]


def _html_to_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


def _collapse(value: str) -> str:
    normalized_lines = [re.sub(r"[\t\f\v ]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in normalized_lines if line)
