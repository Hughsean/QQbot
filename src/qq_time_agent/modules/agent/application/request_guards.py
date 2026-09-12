"""Deterministic guards for low-risk acknowledgements and calendar mutation coverage."""

import json
import re

from qq_time_agent.modules.agent.application.observation_codec import (
    canonicalize_observation_output,
)
from qq_time_agent.modules.agent.contracts import ToolObservation

_ACKNOWLEDGEMENTS = {
    "好",
    "好的",
    "行",
    "行了解",
    "了解",
    "明白",
    "明白了",
    "收到",
    "可以",
    "没问题",
    "嗯",
    "嗯嗯",
    "ok",
    "okay",
    "知道了",
}
_CREATE_INTENT = re.compile(
    r"(?:请.{0,8}(?:创建|新建|添加)|(?:创建|新建|添加).{0,8}(?:日程|提醒)|提醒我)"
)
_SCHEDULE_TIME = re.compile(
    r"(?:\d{1,2}\s*(?:点|时)|\d{1,2}:\d{2}|今天|明天|后天|周[一二三四五六日天])"
)
_ARABIC_COUNT = re.compile(r"(\d{1,2})\s*(?:个|条)")
_CHINESE_COUNT = re.compile(r"([一二两俩三四五六七八九十])\s*(?:个|条)")
_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "俩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def is_short_acknowledgement(message: str) -> bool:
    normalized = re.sub(r"[\s\uff0c\u3002\uff01\uff1f\u3001,.!?]", "", message).casefold()
    return normalized in _ACKNOWLEDGEMENTS


def expected_agenda_creates(message: str) -> int:
    if not _CREATE_INTENT.search(message) or not _SCHEDULE_TIME.search(message):
        return 0
    arabic = _ARABIC_COUNT.search(message)
    if arabic is not None:
        return max(1, min(20, int(arabic.group(1))))
    chinese = _CHINESE_COUNT.search(message)
    if chinese is not None:
        return _CHINESE_NUMBERS[chinese.group(1)]
    return 1


def successful_agenda_creates(observations: list[ToolObservation]) -> int:
    count = 0
    for observation in observations:
        if observation.name != "create_agenda" or observation.is_error:
            continue
        try:
            output = json.loads(str(observation.output))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(output, dict) and output.get("status") == "SUCCEEDED":
            count += 1
    return count


def creation_coverage_observation(step: int, expected: int, succeeded: int) -> ToolObservation:
    return ToolObservation(
        f"creation-coverage-{step}",
        "creation_coverage_guard",
        canonicalize_observation_output(
            {
                "status": "INCOMPLETE",
                "expected_creates": expected,
                "succeeded_creates": succeeded,
                "instruction": "继续调用 create_agenda 完成未执行条目, 不得提前宣称全部成功",
            },
            12_000,
        ),
        True,
    )


def incomplete_creation_reply(expected: int, succeeded: int) -> str:
    if succeeded == 0:
        return (
            f"本次未确认任何日程创建成功(请求 {expected} 条), 因此没有将它们报告为已创建。请重试。"
        )
    return (
        f"本次仅确认成功创建 {succeeded}/{expected} 条日程; "
        "其余条目未确认成功, 请重新发送未完成项。"
    )
