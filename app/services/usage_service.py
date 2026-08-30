from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, desc, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    CostEvent,
    ExternalBudgetReservation,
    ExternalUsage,
    PricingConfig,
    ProviderBudgetPolicy,
    ReservationStatus,
    Vertical,
)


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
                    or_(
                        and_(
                            ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                            ExternalBudgetReservation.expires_at > now,
                        ),
                        and_(
                            ExternalBudgetReservation.status == ReservationStatus.EXPIRED,
                            ExternalBudgetReservation.call_started_at.is_not(None),
                        ),
                        ExternalBudgetReservation.status == ReservationStatus.UNCERTAIN,
                    ),
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
        reservation_key: str | None = None,
        worker_id: str | None = None,
        provider: str | None = None,
    ) -> int:
        if daily_limit <= 0:
            raise ExternalBudgetExceeded(f"Лимит внешних запросов {service} установлен в 0")
        if units <= 0:
            raise ValueError("units must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        async with self._lock:
            now = datetime.now(UTC)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            month_start = start.replace(day=1)
            async with self.session_factory() as session:
                bind = session.get_bind()
                if bind.dialect.name == "sqlite":
                    # SQLite has no row-level SELECT FOR UPDATE. Taking the write lock before
                    # reading serializes the check-and-reserve transaction across processes.
                    await session.execute(text("BEGIN IMMEDIATE"))
                await session.execute(
                    update(ExternalBudgetReservation)
                    .where(
                        ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                        ExternalBudgetReservation.expires_at <= now,
                    )
                    .values(status=ReservationStatus.EXPIRED, finalized_at=now)
                )
                used = await session.scalar(
                    select(func.coalesce(func.sum(ExternalUsage.units), 0)).where(
                        ExternalUsage.service == service,
                        ExternalUsage.created_at >= start,
                    )
                )
                active_res = await session.scalar(
                    select(
                        func.coalesce(func.sum(ExternalBudgetReservation.units_reserved), 0)
                    ).where(
                        ExternalBudgetReservation.service == service,
                        ExternalBudgetReservation.created_at >= start,
                        or_(
                            and_(
                                ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                                ExternalBudgetReservation.expires_at > now,
                            ),
                            and_(
                                ExternalBudgetReservation.status == ReservationStatus.EXPIRED,
                                ExternalBudgetReservation.call_started_at.is_not(None),
                            ),
                            ExternalBudgetReservation.status == ReservationStatus.UNCERTAIN,
                        ),
                    )
                )
                total_committed = int(used or 0) + int(active_res or 0)
                if total_committed + units > daily_limit:
                    raise ExternalBudgetExceeded(
                        f"Дневной лимит {service} исчерпан (использовано: {used}, зарезервировано: {active_res}, лимит: {daily_limit})"
                    )
                normalized_provider = (provider or service).strip().lower()
                monthly_policy = await session.scalar(
                    select(ProviderBudgetPolicy).where(
                        ProviderBudgetPolicy.provider == normalized_provider,
                        ProviderBudgetPolicy.service == service,
                        ProviderBudgetPolicy.active.is_(True),
                    )
                )
                if monthly_policy is not None:
                    monthly_used = await session.scalar(
                        select(func.coalesce(func.sum(CostEvent.units), 0)).where(
                            CostEvent.provider == normalized_provider,
                            CostEvent.created_at >= month_start,
                        )
                    )
                    monthly_active = await session.scalar(
                        select(
                            func.coalesce(
                                func.sum(ExternalBudgetReservation.units_reserved),
                                0,
                            )
                        ).where(
                            ExternalBudgetReservation.provider == normalized_provider,
                            ExternalBudgetReservation.created_at >= month_start,
                            or_(
                                and_(
                                    ExternalBudgetReservation.status
                                    == ReservationStatus.RESERVED,
                                    ExternalBudgetReservation.expires_at > now,
                                ),
                                and_(
                                    ExternalBudgetReservation.status
                                    == ReservationStatus.EXPIRED,
                                    ExternalBudgetReservation.call_started_at.is_not(None),
                                ),
                                ExternalBudgetReservation.status
                                == ReservationStatus.UNCERTAIN,
                            ),
                        )
                    )
                    if (
                        int(monthly_used or 0) + int(monthly_active or 0) + units
                        > monthly_policy.monthly_hard_limit_units
                    ):
                        raise ExternalBudgetExceeded(
                            f"Месячный hard limit {normalized_provider} исчерпан "
                            f"(использовано: {monthly_used}, зарезервировано: "
                            f"{monthly_active}, лимит: "
                            f"{monthly_policy.monthly_hard_limit_units})"
                        )
                reservation = ExternalBudgetReservation(
                    reservation_key=reservation_key or f"reservation:{uuid4().hex}",
                    worker_id=worker_id,
                    service=service,
                    provider=normalized_provider,
                    operation=operation,
                    units_reserved=units,
                    estimated_cost_usd=Decimal(str(estimated_cost)),
                    request_fingerprint=request_fingerprint,
                    status=ReservationStatus.RESERVED,
                    expires_at=now + timedelta(seconds=lease_seconds),
                    reserved_at=now,
                )
                session.add(reservation)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    if reservation_key is None:
                        raise
                    existing = await session.scalar(
                        select(ExternalBudgetReservation).where(
                            ExternalBudgetReservation.reservation_key == reservation_key
                        )
                    )
                    if existing is None:
                        raise
                    return existing.id
                return reservation.id

    async def mark_call_started(self, reservation_id: int) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(ExternalBudgetReservation)
                .where(
                    ExternalBudgetReservation.id == reservation_id,
                    ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                    ExternalBudgetReservation.call_started_at.is_(None),
                )
                .values(call_started_at=datetime.now(UTC))
            )
            await session.commit()

    async def finalize_reservation(
        self,
        reservation_id: int,
        *,
        units: int = 1,
        success: bool = True,
        details: dict[str, Any] | None = None,
        actual_cost: Decimal | float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        vertical: Vertical | None = None,
        competitor_id: int | None = None,
        lead_id: int | None = None,
        audience_id: int | None = None,
        campaign_id: int | None = None,
        unit_source: str = "ESTIMATED",
    ) -> None:
        if units < 0:
            raise ValueError("units must be non-negative")
        now = datetime.now(UTC)
        normalized_source = unit_source.strip().upper()
        if normalized_source not in {"ESTIMATED", "PROVIDER_CONFIRMED"}:
            raise ValueError("unit_source must be ESTIMATED or PROVIDER_CONFIRMED")
        async with self.session_factory() as session:
            stored = await session.get(ExternalBudgetReservation, reservation_id)
            resolved_details = dict(details or {})
            if stored is not None and units > stored.units_reserved:
                resolved_details["reservation_discrepancy"] = {
                    "reserved_units": stored.units_reserved,
                    "actual_units": units,
                    "actual_exceeded_reservation": True,
                }
            reservation = (
                await session.execute(
                    update(ExternalBudgetReservation)
                    .where(
                        ExternalBudgetReservation.id == reservation_id,
                        ExternalBudgetReservation.status.in_(
                            [ReservationStatus.RESERVED, ReservationStatus.EXPIRED]
                        ),
                    )
                    .values(
                        status=ReservationStatus.FINALIZED,
                        finalized_at=now,
                        actual_units=units,
                        actual_cost_usd=(
                            Decimal(str(actual_cost)) if actual_cost is not None else None
                        ),
                        details_json=resolved_details,
                    )
                    .returning(
                        ExternalBudgetReservation.service,
                        ExternalBudgetReservation.operation,
                        ExternalBudgetReservation.reservation_key,
                        ExternalBudgetReservation.provider,
                    )
                )
            ).one_or_none()
            if reservation is not None:
                resolved_cost = (
                    Decimal(str(actual_cost))
                    if actual_cost is not None
                    else await self._price_for(
                        session,
                        provider=reservation[3],
                        operation=reservation[1],
                        units=units,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model_name=str(resolved_details.get("model") or "") or None,
                    )
                )
                await session.execute(
                    update(ExternalBudgetReservation)
                    .where(ExternalBudgetReservation.id == reservation_id)
                    .values(actual_cost_usd=resolved_cost)
                )
                session.add(
                    ExternalUsage(
                        service=reservation[0],
                        operation=reservation[1],
                        idempotency_key=f"reservation:{reservation[2]}",
                        units=units,
                        unit_source=normalized_source,
                        success=success,
                        details_json=resolved_details,
                    )
                )
                session.add(
                    CostEvent(
                        idempotency_key=f"cost:{reservation[2]}",
                        reservation_id=reservation_id,
                        service=reservation[0],
                        provider=reservation[3],
                        operation=reservation[1],
                        vertical=vertical,
                        competitor_id=competitor_id,
                        lead_id=lead_id,
                        audience_id=audience_id,
                        campaign_id=campaign_id,
                        units=units,
                        unit_source=normalized_source,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cost_usd=resolved_cost,
                        details_json=resolved_details,
                    )
                )
                await session.commit()

    async def mark_reservation_uncertain(
        self,
        reservation_id: int,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Зафиксировать неопределённый исход начатого вызова без предположений насчёт списания."""
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            await session.execute(
                update(ExternalBudgetReservation)
                .where(
                    ExternalBudgetReservation.id == reservation_id,
                    ExternalBudgetReservation.status.in_(
                        [ReservationStatus.RESERVED, ReservationStatus.EXPIRED]
                    ),
                    ExternalBudgetReservation.call_started_at.is_not(None),
                )
                .values(
                    status=ReservationStatus.UNCERTAIN,
                    finalized_at=now,
                    details_json=details or {},
                )
            )
            await session.commit()

    async def release_reservation(self, reservation_id: int) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(ExternalBudgetReservation)
                .where(
                    ExternalBudgetReservation.id == reservation_id,
                    ExternalBudgetReservation.status == ReservationStatus.RESERVED,
                    ExternalBudgetReservation.call_started_at.is_(None),
                )
                .values(
                    status=ReservationStatus.RELEASED,
                    finalized_at=datetime.now(UTC),
                    released_at=datetime.now(UTC),
                )
            )
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
        provider: str | None = None,
        cost_usd: Decimal | float | None = None,
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
            event_key = f"legacy:{uuid4().hex}"
            session.add(
                CostEvent(
                    idempotency_key=event_key,
                    service=service,
                    provider=(provider or str((details or {}).get("provider") or service)).lower(),
                    operation=operation,
                    units=units,
                    cost_usd=(Decimal(str(cost_usd)) if cost_usd is not None else None),
                    details_json=details or {},
                )
            )
            await session.commit()

    @staticmethod
    async def _price_for(
        session: AsyncSession,
        *,
        provider: str,
        operation: str,
        units: int,
        input_tokens: int | None,
        output_tokens: int | None,
        model_name: str | None,
    ) -> Decimal | None:
        now = datetime.now(UTC)
        config = await session.scalar(
            select(PricingConfig)
            .where(
                PricingConfig.provider == provider.lower(),
                PricingConfig.operation == operation.lower(),
                PricingConfig.model_name == (model_name.lower() if model_name else ""),
                PricingConfig.active.is_(True),
                PricingConfig.effective_from <= now,
            )
            .order_by(desc(PricingConfig.effective_from))
            .limit(1)
        )
        if config is None:
            return None
        if config.pricing_basis in {"REQUEST", "UNIT"}:
            return config.unit_price * units if config.unit_price is not None else None
        if config.pricing_basis == "TOKENS":
            if input_tokens and config.input_price is None:
                return None
            if output_tokens and config.output_price is None:
                return None
            return (
                (config.input_price or Decimal("0")) * int(input_tokens or 0)
                + (config.output_price or Decimal("0")) * int(output_tokens or 0)
            )
        return None

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
            cost_min = Decimal(str(units)) * Decimal("0.001") + Decimal(str(tokens)) * Decimal(
                "0.0000003"
            )
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
