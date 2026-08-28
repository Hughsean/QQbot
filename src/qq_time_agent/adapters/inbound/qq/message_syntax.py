"""Stateless QQ message parsing and provider-neutral envelope transformations."""

import hashlib
import re

from qq_time_agent.contracts.source import (
    IngressType,
    SourceEnvelope,
    SourceType,
    TrustLevel,
)


def forwarded(content: str) -> tuple[bool, str]:
    value = content.strip()
    for prefix in ("转发:", "转发\N{FULLWIDTH COLON}"):
        if value.startswith(prefix):
            text = value[len(prefix) :].strip()
            if not text:
                raise ValueError("转发文本不能为空")
            return True, text
    match = re.match(
        r"^(?:\[(?:聊天记录|合并转发)\]|【(?:聊天记录|合并转发)】|"
        r"聊天记录(?:\N{FULLWIDTH COLON}|:))\s*",
        value,
    )
    if match is not None:
        text = value[match.end() :].strip()
        if not text:
            raise ValueError("转发文本不能为空")
        return True, text
    return False, value


def noted(content: str) -> tuple[bool, str]:
    value = content.strip()
    for prefix in ("笔记:", "笔记\N{FULLWIDTH COLON}"):
        if value.startswith(prefix):
            note = value[len(prefix) :].strip()
            if not note:
                raise ValueError("笔记文本不能为空")
            return True, note
    return False, value


def questioned(content: str) -> tuple[bool, str]:
    value = content.strip()
    for prefix in ("查询:", "查询\N{FULLWIDTH COLON}"):
        if value.startswith(prefix):
            question = value[len(prefix) :].strip()
            if not question:
                raise ValueError("查询问题不能为空")
            return True, question
    return False, value


def as_forwarded(value: SourceEnvelope, content: str) -> SourceEnvelope:
    return _with_source_type(
        value, content, SourceType.QQ_FORWARD, IngressType.FORWARDED, "forwarded_text"
    )


def as_note(value: SourceEnvelope, content: str) -> SourceEnvelope:
    return _with_source_type(
        value, content, SourceType.OWNER_NOTE, IngressType.DIRECT, "owner_note"
    )


def subject(source_type: SourceType) -> str:
    return {
        SourceType.QQ_FORWARD: "QQ 转发文本",
        SourceType.OWNER_NOTE: "主人笔记",
        SourceType.QQ_DIRECT: "QQ 直接输入",
    }[source_type]


def _with_source_type(
    value: SourceEnvelope,
    content: str,
    source_type: SourceType,
    ingress_type: IngressType,
    message_kind: str,
) -> SourceEnvelope:
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    return SourceEnvelope(
        source_type,
        ingress_type,
        value.external_id,
        value.thread_id,
        value.occurred_at,
        value.received_at,
        value.sender,
        value.content_ref,
        f"sha256:{content_hash}",
        TrustLevel.T2,
        {"message_kind": message_kind},
    )
