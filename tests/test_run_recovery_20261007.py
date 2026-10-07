import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.models import CostEvent, MonitorRun, MonitorRunStatus
from app.services.instagram_monitor import CycleStats
from app.services.monitor_controller import MonitorController
from app.services.monitor_run_service import MonitorRunService
from tests.test_monitor_controller import BlockingMonitor


async def test_cancelled_scan_is_closed_and_retains_recorded_spend(session_factory):
    monitor = BlockingMonitor()
    run_service = MonitorRunService(session_factory, "scrapecreators")
    controller = MonitorController(monitor, run_service)
    assert controller.start_cycle("web", requested_units=5, max_units=5)
    await asyncio.wait_for(monitor.started.wait(), timeout=3)
    async with session_factory() as session:
        session.add(
            CostEvent(
                idempotency_key="cancelled-paid-page",
                service="instagram",
                provider="scrapecreators",
                operation="get_comment_page",
                units=1,
            )
        )
        await session.commit()
    await controller.stop()
    assert "прервана" in controller.snapshot().last_error
    async with session_factory() as session:
        run = await session.scalar(select(MonitorRun))
        assert run.status == MonitorRunStatus.FAILED
        assert run.completed_at is not None
        assert run.actual_credits_spent == 1
        completed_at = run.completed_at
        error = run.error
        run_id = run.id
    await run_service.finish_failure(run_id, RuntimeError("repeat"))
    await run_service.finish_success(run_id, CycleStats())
    async with session_factory() as session:
        run = await session.get(MonitorRun, run_id)
        assert run.completed_at == completed_at
        assert run.error == error
        assert run.status == MonitorRunStatus.FAILED


async def test_run_creation_failure_is_visible_and_never_calls_provider():
    monitor = SimpleNamespace(run_cycle=AsyncMock())
    service = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError("database unavailable")))
    controller = MonitorController(monitor, service)
    assert controller.start_cycle("web")
    with pytest.raises(RuntimeError, match="database unavailable"):
        await controller.wait_current()
    assert not controller.snapshot().cycle_running
    assert "database unavailable" in controller.snapshot().last_error
    assert controller.snapshot().last_cycle_completed_at is not None
    monitor.run_cycle.assert_not_called()


async def test_partial_source_failure_keeps_results_without_reporting_success(session_factory):
    monitor = SimpleNamespace(
        run_cycle=AsyncMock(
            return_value=CycleStats(
                errors=1,
                comments_created=7,
                leads_created=3,
                competitors_checked=2,
            )
        )
    )
    controller = MonitorController(monitor, MonitorRunService(session_factory, "scrapecreators"))
    assert controller.start_cycle("web")
    stats = await controller.wait_current()
    assert stats.comments_created == 7
    assert "ошибками" in controller.snapshot().last_error
    async with session_factory() as session:
        run = await session.scalar(select(MonitorRun))
        assert run.status == MonitorRunStatus.FAILED
        assert run.stats_json["comments_created"] == 7
        assert run.stats_json["errors"] == 1
        assert "Полученные сигналы сохранены" in run.error


async def test_restart_recovers_interrupted_runs_without_counting_later_scan_spend(session_factory):
    now = datetime.now(UTC)
    async with session_factory() as session:
        old = MonitorRun(status=MonitorRunStatus.RUNNING, started_at=now - timedelta(hours=2))
        newer = MonitorRun(
            status=MonitorRunStatus.SUCCESS,
            started_at=now - timedelta(hours=1),
            completed_at=now - timedelta(minutes=50),
            actual_credits_spent=7,
        )
        session.add_all([old, newer])
        session.add_all(
            [
                CostEvent(
                    idempotency_key="old-scan",
                    service="instagram",
                    provider="scrapecreators",
                    operation="get_comment_page",
                    units=2,
                    created_at=now - timedelta(minutes=90),
                ),
                CostEvent(
                    idempotency_key="new-scan",
                    service="instagram",
                    provider="scrapecreators",
                    operation="get_comment_page",
                    units=7,
                    created_at=now - timedelta(minutes=55),
                ),
            ]
        )
        await session.commit()
        old_id, newer_id = old.id, newer.id
    service = MonitorRunService(session_factory, "scrapecreators")
    assert await service.recover_interrupted_runs() == 1
    assert await service.recover_interrupted_runs() == 0
    async with session_factory() as session:
        old = await session.get(MonitorRun, old_id)
        newer = await session.get(MonitorRun, newer_id)
        assert old.status == MonitorRunStatus.FAILED
        assert old.actual_credits_spent == 2
        assert old.operations_json == {"get_comment_page": 2}
        assert newer.status == MonitorRunStatus.SUCCESS
        assert newer.actual_credits_spent == 7


async def test_successful_finalization_is_idempotent(session_factory):
    service = MonitorRunService(session_factory, "mock")
    run_id = await service.start("web")
    await service.finish_success(run_id, CycleStats(comments_created=4))
    async with session_factory() as session:
        run = await session.get(MonitorRun, run_id)
        completed_at = run.completed_at
    await service.finish_success(run_id, CycleStats(comments_created=999))
    async with session_factory() as session:
        run = await session.get(MonitorRun, run_id)
        assert run.stats_json["comments_created"] == 4
        assert run.completed_at == completed_at


async def test_concurrent_finalization_preserves_first_committed_result(file_session_factory):
    first = MonitorRunService(file_session_factory, "mock")
    second = MonitorRunService(file_session_factory, "mock")
    run_id = await first.start("web")
    await asyncio.gather(
        first.finish_success(run_id, CycleStats(comments_created=4)),
        second.finish_failure(run_id, RuntimeError("cancelled concurrently")),
    )
    async with file_session_factory() as session:
        run = await session.get(MonitorRun, run_id)
        saved = (run.status, run.error, run.stats_json, run.completed_at)
    assert saved[0] in {MonitorRunStatus.SUCCESS, MonitorRunStatus.FAILED}
    if saved[0] == MonitorRunStatus.SUCCESS:
        assert saved[1] is None and saved[2]["comments_created"] == 4
    else:
        assert "cancelled concurrently" in saved[1] and saved[2] == {}
    await first.finish_success(run_id, CycleStats(comments_created=999))
    await second.finish_failure(run_id, RuntimeError("overwrite"))
    async with file_session_factory() as session:
        run = await session.get(MonitorRun, run_id)
        assert (run.status, run.error, run.stats_json, run.completed_at) == saved
