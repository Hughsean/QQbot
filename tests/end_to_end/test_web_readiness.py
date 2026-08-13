import asyncio
import socket

import httpx
import pytest
import uvicorn

from qq_time_agent.bootstrap.web import build_app

pytestmark = [pytest.mark.sandbox, pytest.mark.asyncio]


async def test_uvicorn_live_and_ready_on_loopback() -> None:
    app, _, _ = build_app()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    running = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        await _wait_started(server)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready", timeout=100)
        assert live.status_code == 200
        assert ready.status_code == 200
        assert ready.json() == {
            "status": "ready",
            "dependencies": {"database": True, "embeddings": True},
        }
    finally:
        server.should_exit = True
        await running


async def _wait_started(server: uvicorn.Server) -> None:
    for _ in range(100):
        if server.started:
            return
        await asyncio.sleep(0.01)
    raise TimeoutError("Uvicorn did not start")
