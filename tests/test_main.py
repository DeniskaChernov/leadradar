from __future__ import annotations

import asyncio
import sys

import pytest

from app import main as main_module


def test_main_treats_keyboard_interrupt_as_clean_shutdown(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["lead-radar"])

    def interrupt(_awaitable):
        _awaitable.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module.asyncio, "run", interrupt)

    with pytest.raises(SystemExit) as stopped:
        main_module.main()

    assert stopped.value.code == 0


@pytest.mark.parametrize("failure", [None, RuntimeError("server failed")])
async def test_web_wrapper_returns_or_propagates_when_serve_finishes(monkeypatch, failure):
    monkeypatch.setattr(main_module, "_install_shutdown_handlers", lambda *args, **kwargs: None)

    class Server:
        should_exit = False

        async def serve(self):
            if failure:
                raise failure

    server = Server()
    event = asyncio.Event()
    if failure:
        with pytest.raises(RuntimeError, match="server failed"):
            await asyncio.wait_for(main_module._serve_web_until_shutdown(server, event), 1)
    else:
        await asyncio.wait_for(main_module._serve_web_until_shutdown(server, event), 1)
    assert event.is_set()
    assert server.should_exit
    assert not any(task.get_name() == "lead-radar-web-stop" for task in asyncio.all_tasks())


async def test_offline_cli_once_records_exact_result_provenance(monkeypatch, file_session_factory):
    from unittest.mock import AsyncMock

    from sqlalchemy import func, select

    from app.config import Settings
    from app.db.models import CostEvent, MonitorRun, SearchResultOrigin

    engine = file_session_factory.kw["bind"]
    settings = Settings(_env_file=None, database_url=str(engine.url),
        instagram_provider="mock", openai_api_key="", telegram_bot_token="",
        ai_mode="rules", lead_search_enabled=True, process_existing_comments=True,
        competitors=["aiko.uz"])
    monkeypatch.setattr(main_module, "backup_sqlite_database", lambda settings: None)
    monkeypatch.setattr(main_module, "upgrade_database", AsyncMock())
    monkeypatch.setattr(main_module, "configure_logging", lambda settings: None)
    monkeypatch.setattr(main_module, "init_error_monitoring", lambda settings: None)
    monkeypatch.setattr(main_module, "create_engine", lambda settings: engine)
    monkeypatch.setattr(main_module, "create_session_factory", lambda engine: file_session_factory)
    assert await main_module._run_owned(settings, once=True) == 0
    async with file_session_factory() as session:
        run = await session.scalar(select(MonitorRun))
        origins = list(await session.scalars(select(SearchResultOrigin)))
        assert run.result_tracking_version == 1 and run.trigger == "once"
        assert origins and all(o.discovered_run_id == o.lead_run_id == run.id for o in origins)
        assert await session.scalar(select(func.count(CostEvent.id))) == 0


@pytest.mark.parametrize("cancel", [False, True])
async def test_web_wrapper_stops_all_tasks_on_shutdown_or_cancellation(monkeypatch, cancel):
    monkeypatch.setattr(main_module, "_install_shutdown_handlers", lambda *args, **kwargs: None)
    started = asyncio.Event()
    finished = asyncio.Event()
    stop_requested = asyncio.Event()

    class Server:
        @property
        def should_exit(self):
            return stop_requested.is_set()

        @should_exit.setter
        def should_exit(self, value):
            if value:
                stop_requested.set()

        async def serve(self):
            started.set()
            try:
                await stop_requested.wait()
            finally:
                finished.set()

    event = asyncio.Event()
    server = Server()
    task = asyncio.create_task(main_module._serve_web_until_shutdown(server, event))
    await started.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        event.set()
        await asyncio.wait_for(task, 1)
    assert finished.is_set()
    assert server.should_exit
