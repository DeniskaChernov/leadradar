from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.services.instagram_monitor import CycleStats
from app.services.monitor_run_service import MonitorRunService
from app.services.scan_progress import ScanProgress, ScanProgressTracker

if TYPE_CHECKING:
    from app.services.instagram_monitor import InstagramMonitor

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
    progress: ScanProgress


class MonitorController:
    def __init__(self, monitor: InstagramMonitor, run_service: MonitorRunService | None = None) -> None:
        self.monitor = monitor
        self.run_service = run_service
        self.started_at = datetime.now(UTC)
        self.cycles_completed = 0
        self.last_cycle_started_at: datetime | None = None
        self.last_cycle_completed_at: datetime | None = None
        self.last_stats: CycleStats | None = None
        self.last_error: str | None = None
        self._cycle_trigger: str | None = None
        self._requested_credit_budget: int | None = None
        self._effective_credit_budget: int | None = None
        self._task: asyncio.Task[CycleStats] | None = None
        self._progress = ScanProgressTracker()

    def start_cycle(
        self,
        trigger: str,
        *,
        max_units: int | None = None,
        requested_units: int | None = None,
    ) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._cycle_trigger = trigger
        self._requested_credit_budget = requested_units
        self._effective_credit_budget = max_units
        provider = getattr(self.monitor, "provider", None)
        if provider is not None:
            if max_units is not None:
                provider.set_scan_budget_limit(max_units)
            else:
                # Scheduler path: never inherit a prior manual Deep-scan cap.
                provider.restore_default_scan_budget()
        self._progress.reset()
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
        progress = self._progress.snapshot()
        if not running and progress.phase not in {"idle", "done"}:
            progress = ScanProgress()
        return RuntimeSnapshot(
            started_at=self.started_at,
            cycle_running=running,
            cycle_trigger=self._cycle_trigger if running else None,
            cycles_completed=self.cycles_completed,
            last_cycle_started_at=self.last_cycle_started_at,
            last_cycle_completed_at=self.last_cycle_completed_at,
            last_stats=self.last_stats,
            last_error=self.last_error,
            progress=progress,
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
        run_id = None
        if self.run_service is not None:
            run_id = await self.run_service.start(
                self._cycle_trigger or "unknown",
                requested_credit_budget=self._requested_credit_budget,
                effective_credit_budget=self._effective_credit_budget,
            )
        try:
            force = (self._cycle_trigger or "") in {"web", "manual", "bot", "once"}
            parameters = inspect.signature(self.monitor.run_cycle).parameters
            kwargs: dict[str, Any] = {}
            if "force" in parameters:
                kwargs["force"] = force
            if "progress" in parameters:
                kwargs["progress"] = self._progress
            stats = await self.monitor.run_cycle(**kwargs)
            self.last_stats = stats
            self.cycles_completed += 1
            self._progress.set_done()
            self._progress.update_stats(
                competitors_checked=stats.competitors_checked,
                reels_found=stats.reels_found,
                comments_created=stats.comments_created,
                leads_created=stats.leads_created,
            )
            if run_id is not None and self.run_service is not None:
                await self.run_service.finish_success(run_id, stats)
            logger.info(
                "controlled_poll_cycle_complete trigger=%s stats=%s",
                self._cycle_trigger,
                stats,
            )
            return stats
        except Exception as exc:
            if run_id is not None and self.run_service is not None:
                await self.run_service.finish_failure(run_id, exc)
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
