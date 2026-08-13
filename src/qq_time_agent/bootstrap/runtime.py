"""Operating-system runtime compatibility setup."""

import asyncio
import sys


def configure_event_loop_policy() -> None:
    """Use the Windows loop supported by psycopg async connections."""

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
