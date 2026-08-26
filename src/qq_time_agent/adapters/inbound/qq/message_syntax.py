"""Stateless QQ message parsing and provider-neutral envelope transformations."""

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta

from qq_time_agent.contracts.source import (
    IngressType,
    SourceEnvelope,
    SourceType,
    TrustLevel,
)
from qq_time_agent.modules.ai_gateway.contracts import GroundedAnswer


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    name: str
    arguments: tuple[str, ...]


def forwarded(content: str) -> tuple[bool, str]:
    value = content.strip()
    for prefix in ("转发:", "转发\N{FULLWIDTH COLON}"):
        if value.startswith(prefix):
            text = value[len(prefix) :].strip()
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


def format_answer(value: GroundedAnswer) -> str:
    if not value.citations:
        return value.answer
    sources = "\n".join(
        f"- {citation.source_ref} ({citation.occurred_at.date().isoformat()})"
        for citation in value.citations
    )
    return f"{value.answer}\n来源:\n{sources}"


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


def parse_command(content: str) -> ParsedCommand | None:
    parts = tuple(content.split())
    if not parts or parts[0] not in {
        "确认",
        "拒绝",
        "修改",
        "撤销",
        "撤销确认",
        "完成",
        "推迟",
        "删除资料",
        "提醒",
    }:
        return None
    return ParsedCommand(parts[0], parts[1:])


def count(args: tuple[str, ...], expected: int) -> None:
    if len(args) != expected:
        raise ValueError("命令参数数量不正确")


def parse_duration(value: str) -> timedelta:
    normalized = value.strip().lower()
    units = (
        ("天", 24 * 60),
        ("d", 24 * 60),
        ("小时", 60),
        ("h", 60),
        ("分钟", 1),
        ("分", 1),
        ("m", 1),
    )
    for suffix, minutes in units:
        if normalized.endswith(suffix):
            amount = normalized[: -len(suffix)]
            if not amount.isdigit() or int(amount) < 1:
                break
            return timedelta(minutes=int(amount) * minutes)
    raise ValueError("提前时长必须是正整数天、小时或分钟")


def looks_like_time_management(value: str) -> bool:
    markers = (
        "今天",
        "明天",
        "后天",
        "昨天",
        "下周",
        "周一",
        "周二",
        "周三",
        "周四",
        "周五",
        "周六",
        "周日",
        "任务",
        "日程",
        "会议",
        "提醒",
        "截止",
        "安排",
        "改到",
        "几点",
        "上午",
        "下午",
        "晚上",
    )
    if any(marker in value for marker in markers):
        return True
    return any(character.isdigit() for character in value) and any(
        marker in value for marker in ("点", ":", "时", "月", "号", "日")
    )


def natural_reminder(value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(.+?)提前([1-9][0-9]*)(天|小时|分钟)提醒我", value.strip())
    if match is None:
        return None
    return match.group(1).strip(), match.group(2) + match.group(3)


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
