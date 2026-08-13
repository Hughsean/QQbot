"""Small IMAP BODYSTRUCTURE parser and safe body-part selection."""

from dataclasses import dataclass

type Token = str | int | list["Token"] | None


@dataclass(frozen=True, slots=True)
class BodyPart:
    section: str
    content_type: str
    charset: str | None
    encoding: str
    size: int | None
    filename: str | None
    attachment: bool


def parse_bodystructure(value: bytes) -> Token:
    marker = value.upper().find(b"BODYSTRUCTURE ")
    source = value[marker + 14 :] if marker >= 0 else value
    tokens = _tokenize(source)
    result, _ = _parse(tokens, 0)
    return result


def body_parts(root: Token) -> tuple[BodyPart, ...]:
    output: list[BodyPart] = []
    _walk(root, "", output)
    return tuple(output)


def _walk(node: Token, section: str, output: list[BodyPart]) -> None:
    if not isinstance(node, list) or not node:
        return
    if isinstance(node[0], list):
        child_number = 1
        for child in node:
            if not isinstance(child, list):
                break
            path = f"{section}.{child_number}" if section else str(child_number)
            _walk(child, path, output)
            child_number += 1
        return
    if len(node) < 7:
        return
    major = _string(node[0]).lower()
    minor = _string(node[1]).lower()
    params = _parameters(node[2])
    encoding = _string(node[5]).lower() or "7bit"
    size = node[6] if isinstance(node[6], int) else None
    disposition_index = 9 if major == "text" else 8
    disposition, disposition_params = _disposition(node, disposition_index)
    filename = disposition_params.get("filename") or params.get("name")
    attachment = disposition == "attachment" or filename is not None
    output.append(
        BodyPart(
            section or "1",
            f"{major}/{minor}",
            params.get("charset"),
            encoding,
            size,
            filename,
            attachment,
        )
    )


def _disposition(node: list[Token], index: int) -> tuple[str, dict[str, str]]:
    if index >= len(node) or not isinstance(node[index], list):
        return "", {}
    value = node[index]
    assert isinstance(value, list)
    name = _string(value[0]).lower() if value else ""
    return name, _parameters(value[1] if len(value) > 1 else None)


def _parameters(value: Token) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for index in range(0, len(value) - 1, 2):
        key = _string(value[index]).lower()
        if key:
            result[key] = _string(value[index + 1])
    return result


def _string(value: Token) -> str:
    return value if isinstance(value, str) else ""


def _parse(tokens: list[str], index: int) -> tuple[Token, int]:
    if index >= len(tokens):
        raise ValueError("invalid BODYSTRUCTURE")
    current = tokens[index]
    if current != "(":
        if current.upper() == "NIL":
            return None, index + 1
        return (int(current) if current.isdigit() else current), index + 1
    values: list[Token] = []
    index += 1
    while index < len(tokens) and tokens[index] != ")":
        value, index = _parse(tokens, index)
        values.append(value)
    if index >= len(tokens):
        raise ValueError("unclosed BODYSTRUCTURE")
    return values, index + 1


def _tokenize(value: bytes) -> list[str]:
    text = value.decode("utf-8", "replace")
    tokens: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
        elif char in "()":
            tokens.append(char)
            index += 1
        elif char == '"':
            token, index = _quoted(text, index + 1)
            tokens.append(token)
        else:
            end = index
            while end < len(text) and not text[end].isspace() and text[end] not in "()":
                end += 1
            tokens.append(text[index:end])
            index = end
    return tokens


def _quoted(text: str, index: int) -> tuple[str, int]:
    output: list[str] = []
    while index < len(text):
        if text[index] == '"':
            return "".join(output), index + 1
        if text[index] == "\\" and index + 1 < len(text):
            index += 1
        output.append(text[index])
        index += 1
    raise ValueError("unclosed quoted BODYSTRUCTURE value")
