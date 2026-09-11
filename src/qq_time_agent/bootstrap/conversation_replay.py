"""Local-only command for replaying redacted conversation exports."""

from __future__ import annotations

import argparse
import asyncio
import json
from ipaddress import ip_address
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from qq_time_agent.adapters.outbound.persistence.database import create_database_engine
from qq_time_agent.bootstrap.runtime import configure_event_loop_policy
from qq_time_agent.bootstrap.settings import load_runtime_config
from qq_time_agent.contracts.clock import SystemClock
from qq_time_agent.modules.agent.application.conversation_replay import (
    ConversationTimelineReplay,
    ReplayResult,
)
from qq_time_agent.modules.agent.infrastructure.conversation_events import (
    SqlConversationEventRepository,
)


async def replay_conversation(path: Path) -> ReplayResult:
    """Replay one local export after enforcing the local-only boundary."""
    config = load_runtime_config()
    _require_isolated_database(
        config.database.host,
        config.database.name,
        config.app.environment,
    )
    engine = create_database_engine(config.database)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        service = ConversationTimelineReplay(
            SqlConversationEventRepository(sessions), clock=SystemClock()
        )
        return await service.replay_path(path)
    finally:
        await engine.dispose()


def _require_isolated_database(host: str, database_name: str, environment: str) -> None:
    if environment.strip().lower() not in {"test", "replay"}:
        raise RuntimeError("conversation replay requires APP_ENV=test or APP_ENV=replay")
    try:
        local = ip_address(host).is_loopback
    except ValueError:
        local = host.lower() in {"localhost"}
    if not local:
        raise RuntimeError("conversation replay requires a loopback database host")
    normalized_name = database_name.strip().lower()
    if not normalized_name.startswith(("qq_time_agent_replay", "qq_time_agent_test")):
        raise RuntimeError("conversation replay requires a dedicated replay/test database name")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay a redacted conversation export locally")
    parser.add_argument("input", type=Path, help="local JSON or CSV replay input")
    return parser


def main() -> None:
    configure_event_loop_policy()
    result = asyncio.run(replay_conversation(_parser().parse_args().input))
    print(json.dumps(_result_payload(result), ensure_ascii=False, sort_keys=True))


def _result_payload(result: ReplayResult) -> dict[str, object]:
    return {
        "input_count": result.input_count,
        "inserted_count": result.inserted_count,
        "skipped_count": result.skipped_count,
        "failed_count": result.failed_count,
        "user_hashes": result.user_hashes,
        "scope_hashes": result.scope_hashes,
        "sequence_ranges": result.sequence_ranges,
    }


if __name__ == "__main__":
    main()
