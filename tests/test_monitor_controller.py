import asyncio

import pytest

from app.services.instagram_monitor import CycleStats
from app.services.monitor_controller import MonitorController


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


async def test_controller_exposes_cycle_failure():
    controller = MonitorController(FailingMonitor())  # type: ignore[arg-type]

    assert controller.start_cycle("manual") is True
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await controller.wait_current()

    snapshot = controller.snapshot()
    assert snapshot.cycle_running is False
    assert snapshot.cycles_completed == 0
    assert snapshot.last_error == "RuntimeError: provider unavailable"
