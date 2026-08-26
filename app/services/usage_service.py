from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ExternalUsage


class ExternalBudgetExceeded(RuntimeError):
    """Raised before a paid/free-quota external call would exceed the configured budget."""


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    service: str
    used_today: int
    daily_limit: int
    remaining: int


class ExternalUsageService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def used_today(self, service: str) -> int:
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.session_factory() as session:
            value = await session.scalar(
                select(func.coalesce(func.sum(ExternalUsage.units), 0)).where(
                    ExternalUsage.service == service,
                    ExternalUsage.created_at >= start,
                )
            )
            return int(value or 0)

    async def assert_available(self, service: str, daily_limit: int, units: int = 1) -> None:
        if daily_limit <= 0:
            raise ExternalBudgetExceeded(f"Лимит внешних запросов {service} установлен в 0")
        used = await self.used_today(service)
        if used + units > daily_limit:
            raise ExternalBudgetExceeded(
                f"Дневной лимит {service} исчерпан: {used}/{daily_limit}"
            )

    async def record(
        self,
        service: str,
        operation: str,
        *,
        units: int = 1,
        success: bool = True,
        details: dict | None = None,
    ) -> None:
        async with self.session_factory() as session:
            session.add(
                ExternalUsage(
                    service=service,
                    operation=operation,
                    units=units,
                    success=success,
                    details_json=details or {},
                )
            )
            await session.commit()


    async def breakdown_today(self, service: str) -> dict[str, int]:
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.session_factory() as session:
            rows = (
                await session.scalars(
                    select(ExternalUsage).where(
                        ExternalUsage.service == service,
                        ExternalUsage.created_at >= start,
                    )
                )
            ).all()
        result: dict[str, int] = {}
        for row in rows:
            provider = str((row.details_json or {}).get("provider") or "без уточнения")
            result[provider] = result.get(provider, 0) + int(row.units or 0)
        return result

    async def snapshot(self, service: str, daily_limit: int) -> UsageSnapshot:
        used = await self.used_today(service)
        return UsageSnapshot(
            service=service,
            used_today=used,
            daily_limit=daily_limit,
            remaining=max(0, daily_limit - used),
        )
