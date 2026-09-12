"""Structured logging for model failures in the Agent harness."""

import logging
from collections.abc import Awaitable, Callable, Mapping

from qq_time_agent.modules.agent.contracts import ToolObservation

LOGGER = logging.getLogger(__name__)


async def log_model_failure(
    exc: Exception,
    run_id: str,
    step: int,
    observations: list[ToolObservation],
    on_event: Callable[[str, int, Mapping[str, object]], Awaitable[None]] | None,
) -> None:
    if on_event is not None:
        await on_event(
            "FAILED",
            step,
            {"failure_class": type(exc).__name__, "stage": "model"},
        )
    LOGGER.exception(
        "Agent 模型回合失败: 未能获得下一步决策",
        extra={
            "role": "agent",
            "run_id": run_id,
            "step": step,
            "status": "model_failed",
            "failure_class": type(exc).__name__,
            "observation_count": len(observations),
        },
    )
