import pytest

from qq_time_agent.bootstrap.worker import build_worker

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_worker_composition_builds_and_closes_without_polling_external_services() -> None:
    runner, engine, resources = build_worker()
    try:
        assert runner is not None
        assert len(resources) == 6
    finally:
        for resource in resources:
            await resource.close()
        await engine.dispose()
