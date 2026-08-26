from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.instagram_monitor import CycleStats, InstagramMonitor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    started_at: datetime
    cycle_running: bool
    cycle_trigger: str | None
    cycles_completed: int
    last_cycle_started_at: datetime | None
    last_cycle_completed_at: datetime | None
    last_stats: CycleStats | None
    last_error: str | None


class MonitorController:
    def __init__(self, monitor: InstagramMonitor) -> None:
        self.monitor = monitor
        self.started_at = datetime.now(UTC)
        self.cycles_completed = 0
        self.last_cycle_started_at: datetime | None = None
        self.last_cycle_completed_at: datetime | None = None
        self.last_stats: CycleStats | None = None
        self.last_error: str | None = None
        self._cycle_trigger: str | None = None
        self._task: asyncio.Task[CycleStats] | None = None

    def start_cycle(self, trigger: str) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._cycle_trigger = trigger
        self._task = asyncio.create_task(self._execute_cycle(), name=f"monitor:{trigger}")
        self._task.add_done_callback(_consume_task_exception)
        return True

    async def wait_current(self) -> CycleStats | None:
        task = self._task
        if task is None:
            return None
        return await task

    def snapshot(self) -> RuntimeSnapshot:
        running = self._task is not None and not self._task.done()
        return RuntimeSnapshot(
            started_at=self.started_at,
            cycle_running=running,
            cycle_trigger=self._cycle_trigger if running else None,
            cycles_completed=self.cycles_completed,
            last_cycle_started_at=self.last_cycle_started_at,
            last_cycle_completed_at=self.last_cycle_completed_at,
            last_stats=self.last_stats,
            last_error=self.last_error,
        )

    async def stop(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def _execute_cycle(self) -> CycleStats:
        self.last_cycle_started_at = datetime.now(UTC)
        self.last_error = None
        try:
            stats = await self.monitor.run_cycle()
            self.last_stats = stats
            self.cycles_completed += 1
            logger.info(
                "controlled_poll_cycle_complete trigger=%s stats=%s",
                self._cycle_trigger,
                stats,
            )
            return stats
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.exception(
                "controlled_poll_cycle_failed trigger=%s error_type=%s",
                self._cycle_trigger,
                type(exc).__name__,
            )
            raise
        finally:
            self.last_cycle_completed_at = datetime.now(UTC)


def _consume_task_exception(task: asyncio.Task[CycleStats]) -> None:
    if not task.cancelled():
        task.exception()
