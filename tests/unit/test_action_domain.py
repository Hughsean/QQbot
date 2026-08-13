from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qq_time_agent.modules.actions.domain.models import ActionRequest, ActionStatus


def test_action_state_machine_rejects_invalid_states_and_identity() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    action = ActionRequest.request_cancel("owner", uuid4(), 1, now)
    with pytest.raises(PermissionError):
        action.confirm_cancel("intruder", action.confirmation_token)
    action.confirm_cancel("owner", action.confirmation_token)
    action.confirm_cancel("owner", action.confirmation_token)
    action.start()
    action.start()
    action.succeed(uuid4(), 2)
    action.start()
    with pytest.raises(ValueError, match="not executing"):
        action.succeed(uuid4(), 3)
    with pytest.raises(ValueError, match="required"):
        action.fail("failure")


def test_action_required_fields_and_failure_retry() -> None:
    now = datetime(2026, 8, 20, tzinfo=UTC)
    with pytest.raises(ValueError, match="user"):
        ActionRequest.create_agenda(" ", uuid4(), 1, now)
    with pytest.raises(ValueError, match="timezone-aware"):
        ActionRequest.create_agenda("owner", uuid4(), 1, datetime(2026, 8, 20))
    action = ActionRequest.create_agenda("owner", uuid4(), 1, now)
    action.start()
    with pytest.raises(ValueError, match="required"):
        action.fail(" ")
    action.fail("TransientProvider")
    assert action.status is ActionStatus.FAILED
    action.start()
    assert action.failure_class is None
