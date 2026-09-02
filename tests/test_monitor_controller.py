import asyncio

import pytest
from sqlalchemy import select

from app.db.models import MonitorRun
from app.services.instagram_monitor import CycleStats
from app.services.monitor_controller import MonitorController
from app.services.monitor_run_service import MonitorRunService


class BlockingMonitor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def run_cycle(self) -> CycleStats:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return CycleStats(competitors_checked=1, reels_found=11)


class FailingMonitor:
    async def run_cycle(self) -> CycleStats:
        raise RuntimeError("provider unavailable")


class BudgetAwareProvider:
    name = "scrapecreators"

    def __init__(self) -> None:
        self.limit = None
        self.default_restored = 0

    def set_scan_budget_limit(self, limit: int) -> None:
        self.limit = limit

    def restore_default_scan_budget(self) -> None:
        self.limit = "default"
        self.default_restored += 1


class BudgetAwareMonitor:
    def __init__(self) -> None:
        self.provider = BudgetAwareProvider()

    async def run_cycle(self, *, force: bool = False) -> CycleStats:
        return CycleStats(competitors_checked=2, budget_stops=1)


async def test_controller_prevents_overlapping_cycles_and_tracks_status():
    monitor = BlockingMonitor()
    controller = MonitorController(monitor)  # type: ignore[arg-type]

    assert controller.start_cycle("manual") is True
    await monitor.started.wait()
    assert controller.start_cycle("schedule") is False
    assert controller.snapshot().cycle_running is True

    monitor.release.set()
    result = await controller.wait_current()
    snapshot = controller.snapshot()

    assert result is not None
    assert result.reels_found == 11
    assert monitor.calls == 1
    assert snapshot.cycle_running is False
    assert snapshot.cycles_completed == 1
    assert snapshot.last_error is None


async def test_controller_exposes_live_progress_while_running():
    monitor = BlockingMonitor()
    controller = MonitorController(monitor)  # type: ignore[arg-type]

    assert controller.start_cycle("manual") is True
    await monitor.started.wait()
    snap = controller.snapshot()
    assert snap.cycle_running is True
    assert snap.progress.phase == "prepare"
    assert snap.progress.percent >= 1

    monitor.release.set()
    await controller.wait_current()
    done = controller.snapshot()
    assert done.cycle_running is False
    assert done.progress.phase == "done"
    assert done.progress.percent == 100


async def test_controller_exposes_cycle_failure():
    controller = MonitorController(FailingMonitor())  # type: ignore[arg-type]

    assert controller.start_cycle("manual") is True
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await controller.wait_current()

    snapshot = controller.snapshot()
    assert snapshot.cycle_running is False
    assert snapshot.cycles_completed == 0
    assert snapshot.last_error == "RuntimeError: provider unavailable"


async def test_controller_persists_requested_effective_and_actual_run_budget(
    session_factory,
):
    monitor = BudgetAwareMonitor()
    controller = MonitorController(
        monitor,  # type: ignore[arg-type]
        MonitorRunService(session_factory, "scrapecreators"),
    )

    assert controller.start_cycle("web", max_units=7, requested_units=10) is True
    await controller.wait_current()

    async with session_factory() as session:
        run = await session.scalar(select(MonitorRun))
    assert monitor.provider.limit == 7
    assert run is not None
    assert run.requested_credit_budget == 10
    assert run.effective_credit_budget == 7
    assert run.actual_credits_spent == 0
    assert run.budget_stop_reason == "SELECTED_SCAN_LIMIT_REACHED"


async def test_manual_scan_budget_does_not_leak_into_scheduler_cycle():
    monitor = BudgetAwareMonitor()
    controller = MonitorController(monitor)  # type: ignore[arg-type]

    assert controller.start_cycle("web", max_units=40) is True
    await controller.wait_current()
    assert monitor.provider.limit == 40

    assert controller.start_cycle("schedule") is True
    await controller.wait_current()
    assert monitor.provider.limit == "default"
    assert monitor.provider.default_restored == 1
