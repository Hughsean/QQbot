from dataclasses import dataclass

import pytest

from qq_time_agent.adapters.inbound.http.metrics import MetricsService
from qq_time_agent.adapters.outbound.persistence.metrics import _ratio


@dataclass
class Source:
    async def snapshot(self) -> dict[str, float]:
        return {"jobs_pending": 2.0, "deletions_pending": 1.0}


@pytest.mark.asyncio
async def test_metrics_are_stable_aggregates_without_content_labels() -> None:
    rendered = await MetricsService(Source()).render()
    assert rendered == ("qq_time_agent_deletions_pending 1.0\nqq_time_agent_jobs_pending 2.0\n")
    assert "source_ref" not in rendered and "owner" not in rendered


def test_metrics_ratio_is_safe_for_empty_trial_window() -> None:
    assert _ratio(0, 0) == 0.0
    assert _ratio(1, 4) == 0.25
