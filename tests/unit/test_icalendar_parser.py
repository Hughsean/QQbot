from datetime import timedelta

import pytest

from qq_time_agent.modules.normalization.contracts import CalendarChangeKind
from qq_time_agent.modules.normalization.infrastructure.icalendar_parser import IcalendarParser
from qq_time_agent.modules.understanding.application.calendar_mapping import (
    calendar_event_decision,
)


def _calendar(event: str, method: str = "REQUEST") -> bytes:
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//QQ Time Agent//Tests//EN\r\n"
        f"METHOD:{method}\r\n"
        f"{event}"
        "END:VCALENDAR\r\n"
    ).encode()


def test_parses_timezone_dst_participants_and_update_sequence() -> None:
    content = _calendar(
        "BEGIN:VEVENT\r\n"
        "UID:event-1@example.test\r\n"
        "SEQUENCE:2\r\n"
        "DTSTART;TZID=America/New_York:20260308T013000\r\n"
        "DTEND;TZID=America/New_York:20260308T033000\r\n"
        "SUMMARY:Spring transition\r\n"
        "LOCATION:Room 1\r\n"
        "ORGANIZER:mailto:owner@example.test\r\n"
        "ATTENDEE:mailto:guest@example.test\r\n"
        "END:VEVENT\r\n"
    )
    result = IcalendarParser().parse(content, "Asia/Shanghai")
    event = result.events[0]
    assert result.method == "REQUEST" and event.sequence == 2
    assert event.timezone == "America/New_York"
    assert event.starts_at is not None and event.ends_at is not None
    assert event.starts_at.utcoffset() == timedelta(hours=-5)
    assert event.ends_at.utcoffset() == timedelta(hours=-4)
    assert event.participants == ("guest@example.test", "owner@example.test")


def test_parses_all_day_and_applies_exclusive_end() -> None:
    event = (
        IcalendarParser()
        .parse(
            _calendar(
                "BEGIN:VEVENT\r\n"
                "UID:all-day\r\n"
                "DTSTART;VALUE=DATE:20260820\r\n"
                "DTEND;VALUE=DATE:20260822\r\n"
                "SUMMARY:Offsite\r\n"
                "END:VEVENT\r\n"
            ),
            "Asia/Shanghai",
        )
        .events[0]
    )
    assert event.all_day and event.timezone == "Asia/Shanghai"
    assert event.starts_at is not None and event.ends_at is not None
    assert event.ends_at - event.starts_at == timedelta(days=2)


def test_preserves_bounded_recurrence_and_exception_sets() -> None:
    event = (
        IcalendarParser()
        .parse(
            _calendar(
                "BEGIN:VEVENT\r\n"
                "UID:recurring\r\n"
                "DTSTART;TZID=Asia/Shanghai:20260817T090000\r\n"
                "DTEND;TZID=Asia/Shanghai:20260817T100000\r\n"
                "RECURRENCE-ID;TZID=Asia/Shanghai:20260817T090000\r\n"
                "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=MO\r\n"
                "RDATE;TZID=Asia/Shanghai:20260907T090000\r\n"
                "EXDATE;TZID=Asia/Shanghai:20260824T090000\r\n"
                "SUMMARY:Weekly review\r\n"
                "END:VEVENT\r\n"
            ),
            "UTC",
        )
        .events[0]
    )
    assert event.recurrence_rule == "FREQ=WEEKLY;COUNT=3;BYDAY=MO"
    assert len(event.recurrence_dates) == len(event.excluded_dates) == 1
    assert event.recurrence_id == event.starts_at
    decision = calendar_event_decision(event)
    assert decision.draft is not None and decision.model_calls == 0
    assert decision.draft.assumptions == (
        "重复规则已保留;本次确认只处理首个事件时段",
        "这是外部日历更新;执行前需按来源匹配现有日程",
    )


def test_cancel_is_parsed_without_time_and_never_becomes_create_candidate() -> None:
    event = (
        IcalendarParser()
        .parse(
            _calendar(
                "BEGIN:VEVENT\r\n"
                "UID:event-to-cancel\r\n"
                "SEQUENCE:4\r\n"
                "STATUS:CANCELLED\r\n"
                "END:VEVENT\r\n",
                method="CANCEL",
            ),
            "UTC",
        )
        .events[0]
    )
    assert event.change_kind is CalendarChangeKind.CANCEL
    assert event.starts_at is None and event.ends_at is None
    decision = calendar_event_decision(event)
    assert decision.draft is None
    assert decision.review_reason == "calendar_cancellation_requires_existing_match"


def test_missing_end_uses_explicit_deterministic_defaults() -> None:
    timed = (
        IcalendarParser()
        .parse(
            _calendar("BEGIN:VEVENT\r\nUID:timed\r\nDTSTART:20260817T010000Z\r\nEND:VEVENT\r\n"),
            "Asia/Shanghai",
        )
        .events[0]
    )
    all_day = (
        IcalendarParser()
        .parse(
            _calendar("BEGIN:VEVENT\r\nUID:day\r\nDTSTART;VALUE=DATE:20260817\r\nEND:VEVENT\r\n"),
            "Asia/Shanghai",
        )
        .events[0]
    )
    assert timed.starts_at is not None and timed.ends_at is not None
    assert all_day.starts_at is not None and all_day.ends_at is not None
    assert timed.ends_at - timed.starts_at == timedelta(minutes=30)
    assert all_day.ends_at - all_day.starts_at == timedelta(days=1)


def test_rejects_malformed_oversized_and_excess_event_content() -> None:
    parser = IcalendarParser(max_bytes=100, max_events=1)
    with pytest.raises(ValueError, match="size limit"):
        parser.parse(b"x" * 101, "UTC")
    with pytest.raises(ValueError, match="event count"):
        IcalendarParser().parse(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", "UTC")
    two_events = _calendar(
        "BEGIN:VEVENT\r\nUID:one\r\nDTSTART:20260817T010000Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:two\r\nDTSTART:20260818T010000Z\r\nEND:VEVENT\r\n"
    )
    with pytest.raises(ValueError, match="event count"):
        IcalendarParser(max_events=1).parse(two_events, "UTC")
    oversized_field = _calendar(
        "BEGIN:VEVENT\r\nUID:large\r\nDTSTART:20260817T010000Z\r\n"
        f"SUMMARY:{'x' * 2001}\r\nEND:VEVENT\r\n"
    )
    with pytest.raises(ValueError, match="text field"):
        IcalendarParser().parse(oversized_field, "UTC")
    unsupported_method = _calendar(
        "BEGIN:VEVENT\r\nUID:bad-method\r\nDTSTART:20260817T010000Z\r\nEND:VEVENT\r\n",
        method="EXECUTE",
    )
    with pytest.raises(ValueError, match="method"):
        IcalendarParser().parse(unsupported_method, "UTC")


def test_rejects_unknown_default_timezone_and_invalid_event_order() -> None:
    content = _calendar(
        "BEGIN:VEVENT\r\n"
        "UID:bad-order\r\n"
        "DTSTART:20260817T020000Z\r\n"
        "DTEND:20260817T010000Z\r\n"
        "END:VEVENT\r\n"
    )
    with pytest.raises(ValueError, match="timezone"):
        IcalendarParser().parse(content, "Not/AZone")
    with pytest.raises(ValueError, match="after start"):
        IcalendarParser().parse(content, "UTC")


def test_embedded_non_iana_vtimezone_is_canonicalized_to_owner_zone() -> None:
    content = _calendar(
        "BEGIN:VTIMEZONE\r\n"
        "TZID:Custom/Test\r\n"
        "BEGIN:STANDARD\r\n"
        "DTSTART:19700101T000000\r\n"
        "TZOFFSETFROM:+0800\r\n"
        "TZOFFSETTO:+0800\r\n"
        "END:STANDARD\r\n"
        "END:VTIMEZONE\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:custom-zone\r\n"
        "DTSTART;TZID=Custom/Test:20260817T090000\r\n"
        "DTEND;TZID=Custom/Test:20260817T100000\r\n"
        "END:VEVENT\r\n"
    )
    event = IcalendarParser().parse(content, "Asia/Shanghai").events[0]
    assert event.timezone == "Asia/Shanghai"
    assert event.starts_at is not None and event.starts_at.hour == 9
