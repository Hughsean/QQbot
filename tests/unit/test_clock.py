from datetime import UTC

from qq_time_agent.contracts.clock import SystemClock


def test_system_clock_returns_canonical_utc_instant() -> None:
    value = SystemClock().now()
    assert value.tzinfo is UTC
    offset = value.utcoffset()
    assert offset is not None and offset.total_seconds() == 0
