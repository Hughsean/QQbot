import asyncio
import sys

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--sandbox",
        action="store_true",
        default=False,
        help="run tests that call explicitly configured external sandboxes",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--sandbox"):
        return
    skip = pytest.mark.skip(reason="requires explicit --sandbox opt-in")
    for item in items:
        if "sandbox" in item.keywords:
            item.add_marker(skip)
