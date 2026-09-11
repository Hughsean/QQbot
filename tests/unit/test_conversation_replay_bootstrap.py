from qq_time_agent.bootstrap.conversation_replay import _require_isolated_database


def test_replay_bootstrap_accepts_loopback_hosts() -> None:
    _require_isolated_database("127.0.0.1", "qq_time_agent_replay", "replay")
    _require_isolated_database("localhost", "qq_time_agent_test_01", "test")


def test_replay_bootstrap_rejects_production() -> None:
    try:
        _require_isolated_database("127.0.0.1", "qq_time_agent_replay", "production")
    except RuntimeError as exc:
        assert "APP_ENV" in str(exc)
    else:
        raise AssertionError("production replay must be rejected")


def test_replay_bootstrap_rejects_non_loopback_database() -> None:
    try:
        _require_isolated_database("postgres.internal", "qq_time_agent_replay", "replay")
    except RuntimeError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback replay must be rejected")


def test_replay_bootstrap_rejects_shared_database_name() -> None:
    try:
        _require_isolated_database("127.0.0.1", "qq_time_agent", "replay")
    except RuntimeError as exc:
        assert "dedicated" in str(exc)
    else:
        raise AssertionError("shared database must be rejected")
