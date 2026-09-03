"""Фикстуры browser e2e: uvicorn на localhost + Playwright Chromium."""

from __future__ import annotations

import asyncio
import socket

import pytest
import uvicorn

from tests.e2e.helpers import build_e2e_app


@pytest.fixture
async def e2e_base_url(session_factory):
    app = build_e2e_app(session_factory)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()

    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    else:
        server.should_exit = True
        await task
        raise RuntimeError("Не удалось поднять uvicorn для Playwright e2e")

    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=15)
