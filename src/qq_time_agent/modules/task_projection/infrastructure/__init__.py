"""Task projection persistence adapters."""

from qq_time_agent.modules.task_projection.infrastructure.repository import (
    SqlTaskProjectionMappingRepository,
    SqlTaskProjectionTargetRepository,
)

__all__ = ["SqlTaskProjectionMappingRepository", "SqlTaskProjectionTargetRepository"]
