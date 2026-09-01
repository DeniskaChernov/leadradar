"""Фоновая очередь разбора лидов: OpenAI не блокирует цикл Instagram-мониторинга."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from app.db.models import Lead, LeadStatus
from app.services.lead_service import LeadService
from app.services.notification_service import LeadNotifier

logger = logging.getLogger(__name__)

_STALE_ANALYZING_SECONDS = 900


@dataclass(frozen=True, slots=True)
class AnalysisJob:
    lead_id: int
    initial_already_sent: bool = False


class LeadAnalysisPipeline:
    """Bounded-concurrency worker pool для analyze_lead + post-analysis notify."""

    def __init__(
        self,
        lead_service: LeadService,
        notifier: LeadNotifier,
        *,
        max_concurrency: int = 3,
        sync_mode: bool = False,
    ) -> None:
        self.lead_service = lead_service
        self.notifier = notifier
        self.max_concurrency = max(1, max_concurrency)
        self.sync_mode = sync_mode
        self._queue: asyncio.Queue[AnalysisJob | None] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._queued_ids: set[int] = set()
        self._in_flight = 0
        self._concurrency_sem = asyncio.Semaphore(self.max_concurrency)
        self._idle = asyncio.Event()
        self._idle.set()

    async def set_max_concurrency(self, value: int) -> None:
        """Hot-reload лимита параллельных OpenAI-разборов."""
        self.max_concurrency = max(1, min(10, int(value)))
        self._concurrency_sem = asyncio.Semaphore(self.max_concurrency)

    @property
    def pending_count(self) -> int:
        return len(self._queued_ids)

    @property
    def in_flight_count(self) -> int:
        return self._in_flight

    async def start(self) -> None:
        if self._workers:
            return
        self._queue = asyncio.Queue()
        self._concurrency_sem = asyncio.Semaphore(self.max_concurrency)
        for index in range(min(10, max(self.max_concurrency, 3))):
            self._workers.append(
                asyncio.create_task(self._worker(index), name=f"lead-analysis:{index}")
            )

    async def stop(self) -> None:
        if not self._workers or self._queue is None:
            return
        for _ in self._workers:
            await self._queue.put(None)
        for task in self._workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._workers.clear()
        self._queue = None
        self._queued_ids.clear()
        self._in_flight = 0
        self._idle.set()

    async def enqueue(
        self,
        lead_id: int,
        *,
        initial_already_sent: bool = False,
        stats: object | None = None,
    ) -> None:
        """Поставить лид в очередь разбора. sync_mode — выполнить сразу (для тестов)."""
        if lead_id in self._queued_ids:
            return
        job = AnalysisJob(lead_id=lead_id, initial_already_sent=initial_already_sent)
        if self.sync_mode:
            await self._process_job(job, stats=stats)
            return
        await self.start()
        assert self._queue is not None
        self._queued_ids.add(lead_id)
        self._idle.clear()
        await self._queue.put((job, stats))

    async def enqueue_retry_batch(
        self,
        limit: int,
        *,
        cooldown_seconds: int = 0,
    ) -> int:
        """Поставить AI_PENDING / stale ANALYZING в очередь без блокировки HTTP."""
        lead_ids = await self.lead_service.list_pending_lead_ids(
            limit,
            cooldown_seconds=cooldown_seconds,
        )
        added = 0
        for lead_id in lead_ids:
            if lead_id in self._queued_ids:
                continue
            await self.enqueue(lead_id)
            added += 1
        return added

    async def enqueue_pending_batch(self, limit: int = 10) -> int:
        """Добрать AI_PENDING / зависший ANALYZING в очередь без повторного analyze."""
        if limit <= 0:
            return 0
        stale = datetime.now(UTC) - timedelta(seconds=_STALE_ANALYZING_SECONDS)
        async with self.lead_service.session_factory() as session:
            lead_ids = (
                await session.scalars(
                    select(Lead.id)
                    .where(
                        or_(
                            Lead.status == LeadStatus.AI_PENDING,
                            (Lead.status == LeadStatus.ANALYZING)
                            & (
                                Lead.ai_last_attempt_at.is_(None)
                                | (Lead.ai_last_attempt_at <= stale)
                            ),
                        )
                    )
                    .order_by(Lead.created_at)
                    .limit(limit)
                )
            ).all()
        added = 0
        for lead_id in lead_ids:
            if lead_id in self._queued_ids:
                continue
            await self.enqueue(lead_id)
            added += 1
        return added

    async def flush(self) -> None:
        """Дождаться опустошения очереди (тесты и graceful shutdown)."""
        if self.sync_mode or self._queue is None:
            return
        await self._idle.wait()

    async def _worker(self, index: int) -> None:
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            job, stats = item
            async with self._concurrency_sem:
                self._in_flight += 1
                try:
                    await self._process_job(job, stats=stats)
                except Exception:
                    logger.exception(
                        "lead_analysis_worker_failed worker=%s lead_id=%s",
                        index,
                        job.lead_id,
                    )
                finally:
                    self._queued_ids.discard(job.lead_id)
                    self._in_flight -= 1
            self._queue.task_done()
            if self._queue.empty() and self._in_flight == 0:
                self._idle.set()

    async def _process_job(self, job: AnalysisJob, *, stats: object | None = None) -> None:
        analyzed = await self.lead_service.analyze_lead(job.lead_id)
        try:
            sent = await self._notify_analyzed(
                analyzed.lead_id,
                analyzed.is_hot,
                initial_already_sent=job.initial_already_sent,
            )
            if stats is not None and hasattr(stats, "hot_notifications"):
                stats.hot_notifications += sent
            if analyzed.significant_change_id is not None:
                change_sent = await self._notify_significant_change(analyzed.significant_change_id)
                if stats is not None and hasattr(stats, "change_notifications"):
                    stats.change_notifications += change_sent
        except Exception as exc:
            if stats is not None and hasattr(stats, "errors"):
                stats.errors += 1
            logger.exception(
                "lead_analysis_notification_failed lead_id=%s error_type=%s",
                analyzed.lead_id,
                type(exc).__name__,
            )

    async def _notify_analyzed(
        self, lead_id: int, is_hot: bool, *, initial_already_sent: bool = False
    ) -> int:
        notify = getattr(self.notifier, "notify_analyzed_lead", None)
        if notify is not None:
            return await notify(lead_id)
        if is_hot and not initial_already_sent:
            return await self.notifier.notify_hot_lead(lead_id)
        return 0

    async def _notify_significant_change(self, change_id: int) -> int:
        notify = getattr(self.notifier, "notify_significant_change", None)
        if notify is None:
            return 0
        return await notify(change_id)
