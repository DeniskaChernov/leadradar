"""Операционные тумблеры Live Radar / OpenAI — source of truth в БД, кэш в процессе."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OperationalControl


@dataclass(frozen=True, slots=True)
class OperationalSnapshot:
    radar_live_armed: bool
    openai_live_armed: bool
    default_scan_credits: int
    ai_analysis_max_concurrency: int
    updated_by: int | None
    updated_at: datetime | None


_DEFAULT = OperationalSnapshot(
    radar_live_armed=False,
    openai_live_armed=False,
    default_scan_credits=5,
    ai_analysis_max_concurrency=3,
    updated_by=None,
    updated_at=None,
)


class OperationalControlService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._cache: OperationalSnapshot = _DEFAULT

    def snapshot(self) -> OperationalSnapshot:
        return self._cache

    def radar_live_armed(self) -> bool:
        return self._cache.radar_live_armed

    def openai_live_armed(self) -> bool:
        return self._cache.openai_live_armed

    async def load(self) -> OperationalSnapshot:
        async with self.session_factory() as session:
            row = await session.get(OperationalControl, 1)
            if row is None:
                row = OperationalControl(
                    id=1,
                    radar_live_armed=False,
                    openai_live_armed=False,
                    default_scan_credits=5,
                    ai_analysis_max_concurrency=3,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
            self._cache = self._from_row(row)
            return self._cache

    async def set_radar_live(
        self,
        armed: bool,
        *,
        manager_id: int | None = None,
        default_scan_credits: int | None = None,
    ) -> OperationalSnapshot:
        async with self.session_factory() as session:
            row = await self._get_or_create(session)
            row.radar_live_armed = bool(armed)
            if default_scan_credits is not None:
                row.default_scan_credits = max(1, min(50, int(default_scan_credits)))
            row.updated_by = manager_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            self._cache = self._from_row(row)
            return self._cache

    async def set_openai_live(
        self,
        armed: bool,
        *,
        manager_id: int | None = None,
    ) -> OperationalSnapshot:
        async with self.session_factory() as session:
            row = await self._get_or_create(session)
            row.openai_live_armed = bool(armed)
            row.updated_by = manager_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            self._cache = self._from_row(row)
            return self._cache

    async def set_ai_analysis_concurrency(
        self,
        max_concurrency: int,
        *,
        manager_id: int | None = None,
    ) -> OperationalSnapshot:
        async with self.session_factory() as session:
            row = await self._get_or_create(session)
            row.ai_analysis_max_concurrency = max(1, min(10, int(max_concurrency)))
            row.updated_by = manager_id
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            self._cache = self._from_row(row)
            return self._cache

    async def _get_or_create(self, session: AsyncSession) -> OperationalControl:
        row = await session.get(OperationalControl, 1)
        if row is None:
            row = OperationalControl(
                id=1,
                radar_live_armed=False,
                openai_live_armed=False,
                default_scan_credits=5,
                ai_analysis_max_concurrency=3,
            )
            session.add(row)
            await session.flush()
        return row

    @staticmethod
    def _from_row(row: OperationalControl) -> OperationalSnapshot:
        return OperationalSnapshot(
            radar_live_armed=bool(row.radar_live_armed),
            openai_live_armed=bool(row.openai_live_armed),
            default_scan_credits=int(row.default_scan_credits),
            ai_analysis_max_concurrency=int(getattr(row, "ai_analysis_max_concurrency", 3) or 3),
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )
