from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ExternalBudgetReservation, ExternalUsage, ReservationStatus


class ExternalBudgetExceeded(RuntimeError):
    """Raised before a paid/free-quota external call would exceed the configured budget."""


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    service: str
    used_today: int
    daily_limit: int
    remaining: int


@dataclass(frozen=True, slots=True)
class CostPreview:
    operation: str
    estimated_records: int
    estimated_units: int
    estimated_openai_calls: int
    estimated_tokens: int
    estimated_cost_usd_min: Decimal
    estimated_cost_usd_max: Decimal


class ExternalUsageService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._lock = asyncio.Lock()

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

    async def active_reservations_today(self, service: str) -> int:
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.session_factory() as session:
            value = await session.scalar(
                select(func.coalesce(func.sum(ExternalBudgetReservation.units_reserved), 0)).where(
                    ExternalBudgetReservation.service == service,
                    ExternalBudgetReservation.created_at >= start,
                    ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                    ExternalBudgetReservation.expires_at > now,
                )
            )
            return int(value or 0)

    async def reserve_budget(
        self,
        service: str,
        operation: str,
        daily_limit: int,
        *,
        units: int = 1,
        estimated_cost: Decimal | float = 0.0,
        request_fingerprint: str | None = None,
        lease_seconds: int = 60,
    ) -> int:
        if daily_limit <= 0:
            raise ExternalBudgetExceeded(f"Лимит внешних запросов {service} установлен в 0")
        async with self._lock:
            now = datetime.now(UTC)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            async with self.session_factory() as session:
                used = await session.scalar(
                    select(func.coalesce(func.sum(ExternalUsage.units), 0)).where(
                        ExternalUsage.service == service,
                        ExternalUsage.created_at >= start,
                    )
                )
                active_res = await session.scalar(
                    select(func.coalesce(func.sum(ExternalBudgetReservation.units_reserved), 0)).where(
                        ExternalBudgetReservation.service == service,
                        ExternalBudgetReservation.created_at >= start,
                        ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                        ExternalBudgetReservation.expires_at > now,
                    )
                )
                total_committed = int(used or 0) + int(active_res or 0)
                if total_committed + units > daily_limit:
                    raise ExternalBudgetExceeded(
                        f"Дневной лимит {service} исчерпан (использовано: {used}, зарезервировано: {active_res}, лимит: {daily_limit})"
                    )
                reservation = ExternalBudgetReservation(
                    service=service,
                    operation=operation,
                    units_reserved=units,
                    estimated_cost_usd=Decimal(str(estimated_cost)),
                    request_fingerprint=request_fingerprint,
                    status=ReservationStatus.RESERVED,
                    expires_at=now + timedelta(seconds=lease_seconds),
                )
                session.add(reservation)
                await session.commit()
                return reservation.id


    async def finalize_reservation(
        self,
        reservation_id: int,
        *,
        units: int = 1,
        success: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            reservation = await session.get(ExternalBudgetReservation, reservation_id)
            if reservation is not None and reservation.status == ReservationStatus.RESERVED:
                reservation.status = ReservationStatus.FINALIZED
                reservation.finalized_at = now
                session.add(
                    ExternalUsage(
                        service=reservation.service,
                        operation=reservation.operation,
                        units=units,
                        success=success,
                        details_json=details or {},
                    )
                )
                await session.commit()

    async def release_reservation(self, reservation_id: int) -> None:
        async with self.session_factory() as session:
            reservation = await session.get(ExternalBudgetReservation, reservation_id)
            if reservation is not None and reservation.status == ReservationStatus.RESERVED:
                reservation.status = ReservationStatus.RELEASED
                await session.commit()

    async def assert_available(self, service: str, daily_limit: int, units: int = 1) -> None:
        if daily_limit <= 0:
            raise ExternalBudgetExceeded(f"Лимит внешних запросов {service} установлен в 0")
        used = await self.used_today(service)
        active_res = await self.active_reservations_today(service)
        if used + active_res + units > daily_limit:
            raise ExternalBudgetExceeded(
                f"Дневной лимит {service} исчерпан: {used + active_res}/{daily_limit}"
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
        active_res = await self.active_reservations_today(service)
        total = used + active_res
        return UsageSnapshot(
            service=service,
            used_today=total,
            daily_limit=daily_limit,
            remaining=max(0, daily_limit - total),
        )

    @staticmethod
    def preview_cost(
        operation: str, records_count: int, *, provider: str = "scrapecreators"
    ) -> CostPreview:
        """Calculate estimated cost preview before starting any bulk operation."""
        if operation == "followers_scan":
            units = (records_count + 49) // 50
            calls = max(1, records_count // 100)
            tokens = calls * 650
            cost_min = Decimal(str(units)) * Decimal("0.001") + Decimal(str(tokens)) * Decimal("0.0000003")
            cost_max = cost_min * Decimal("1.25")
        elif operation == "historical_backfill":
            units = (records_count + 19) // 20
            calls = records_count
            tokens = calls * 750
            cost_min = Decimal(str(tokens)) * Decimal("0.0000003")
            cost_max = cost_min * Decimal("1.30")
        else:
            units = records_count
            calls = records_count
            tokens = calls * 500
            cost_min = Decimal(str(records_count)) * Decimal("0.0005")
            cost_max = cost_min * Decimal("1.20")

        return CostPreview(
            operation=operation,
            estimated_records=records_count,
            estimated_units=units,
            estimated_openai_calls=calls,
            estimated_tokens=tokens,
            estimated_cost_usd_min=cost_min.quantize(Decimal("0.0001")),
            estimated_cost_usd_max=cost_max.quantize(Decimal("0.0001")),
        )

