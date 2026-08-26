from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import MonitorRun, MonitorRunStatus
from app.services.instagram_monitor import CycleStats


class MonitorRunService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], provider_name: str) -> None:
        self.session_factory = session_factory
        self.provider_name = provider_name

    async def start(self, trigger: str) -> int:
        async with self.session_factory() as session:
            run = MonitorRun(
                trigger=trigger,
                provider=self.provider_name,
                status=MonitorRunStatus.RUNNING,
                stats_json={},
                started_at=datetime.now(UTC),
            )
            session.add(run)
            await session.commit()
            return run.id

    async def finish_success(self, run_id: int, stats: CycleStats) -> None:
        async with self.session_factory() as session:
            run = await session.get(MonitorRun, run_id)
            if run is None:
                return
            run.status = MonitorRunStatus.SUCCESS
            run.stats_json = asdict(stats)
            run.completed_at = datetime.now(UTC)
            await session.commit()

    async def finish_failure(self, run_id: int, exc: Exception) -> None:
        async with self.session_factory() as session:
            run = await session.get(MonitorRun, run_id)
            if run is None:
                return
            run.status = MonitorRunStatus.FAILED
            run.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            run.completed_at = datetime.now(UTC)
            await session.commit()
