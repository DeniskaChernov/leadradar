from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    CostEvent,
    ExternalBudgetReservation,
    ProviderBudgetPolicy,
    ProviderCreditSnapshot,
    ReservationStatus,
)


@dataclass(frozen=True, slots=True)
class ScanBudgetAvailability:
    requested_units: int
    effective_units: int
    daily_remaining: int
    monthly_remaining: int
    provider_balance: int | None
    provider_balance_source: str
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderBudgetSnapshot:
    provider: str
    service: str
    credits_remaining: int | None
    credits_remaining_source: str
    used_this_month: int
    monthly_target: int
    monthly_soft_limit: int
    monthly_hard_limit: int
    monthly_remaining: int
    average_daily_burn_7d: float
    average_daily_burn_30d: float
    projected_monthly_burn: float
    months_remaining: float | None
    months_remaining_at_target: float | None
    budget_status: str
    usage_by_operation: dict[str, int]


class ProviderCreditBudgetService:
    """DB-backed бюджет credits без внешних запросов и недоказанных балансов."""

    CONFIRMED_SOURCES: ClassVar[frozenset[str]] = frozenset(
        {"API_RESPONSE", "BALANCE_ENDPOINT"}
    )

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def policy(
        self,
        provider: str,
        service: str = "instagram",
    ) -> ProviderBudgetPolicy | None:
        async with self.session_factory() as session:
            return await session.scalar(
                select(ProviderBudgetPolicy).where(
                    ProviderBudgetPolicy.provider == provider.strip().lower(),
                    ProviderBudgetPolicy.service == service.strip().lower(),
                    ProviderBudgetPolicy.active.is_(True),
                )
            )

    async def latest_balance(
        self,
        provider: str,
    ) -> ProviderCreditSnapshot | None:
        priority = case(
            (ProviderCreditSnapshot.source.in_(self.CONFIRMED_SOURCES), 0),
            (ProviderCreditSnapshot.source == "MANUAL", 1),
            else_=2,
        )
        async with self.session_factory() as session:
            return await session.scalar(
                select(ProviderCreditSnapshot)
                .where(
                    ProviderCreditSnapshot.provider == provider.strip().lower(),
                    ProviderCreditSnapshot.credits_remaining.is_not(None),
                )
                .order_by(priority, desc(ProviderCreditSnapshot.observed_at))
                .limit(1)
            )

    async def record_credit_snapshot(
        self,
        *,
        idempotency_key: str,
        provider: str,
        operation: str,
        source: str,
        credits_remaining: int | None,
        credits_charged: int | None,
        monitor_run_id: int | None = None,
        observed_at: datetime | None = None,
    ) -> ProviderCreditSnapshot:
        if credits_remaining is None and credits_charged is None:
            raise ValueError("Нельзя сохранить пустой credit snapshot")
        if credits_remaining is not None and credits_remaining < 0:
            raise ValueError("credits_remaining не может быть отрицательным")
        if credits_charged is not None and credits_charged < 0:
            raise ValueError("credits_charged не может быть отрицательным")
        normalized_source = source.strip().upper()
        if normalized_source not in {
            "API_RESPONSE",
            "BALANCE_ENDPOINT",
            "MANUAL",
            "LOCAL_ESTIMATE",
        }:
            raise ValueError("Неизвестный источник credit snapshot")

        async with self.session_factory() as session:
            existing = await session.scalar(
                select(ProviderCreditSnapshot).where(
                    ProviderCreditSnapshot.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return existing
            snapshot = ProviderCreditSnapshot(
                idempotency_key=idempotency_key,
                provider=provider.strip().lower(),
                credits_remaining=credits_remaining,
                credits_charged=credits_charged,
                operation=operation.strip().lower(),
                source=normalized_source,
                observed_at=observed_at or datetime.now(UTC),
                monitor_run_id=monitor_run_id,
            )
            session.add(snapshot)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(ProviderCreditSnapshot).where(
                        ProviderCreditSnapshot.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                return existing
            return snapshot

    async def current_month_usage(self, provider: str) -> int:
        start, _end = self._month_bounds(datetime.now(UTC))
        async with self.session_factory() as session:
            value = await session.scalar(
                select(func.coalesce(func.sum(CostEvent.units), 0)).where(
                    CostEvent.provider == provider.strip().lower(),
                    CostEvent.created_at >= start,
                )
            )
        return int(value or 0)

    async def active_month_reservations(self, provider: str) -> int:
        now = datetime.now(UTC)
        start, _end = self._month_bounds(now)
        async with self.session_factory() as session:
            value = await session.scalar(
                select(
                    func.coalesce(func.sum(ExternalBudgetReservation.units_reserved), 0)
                ).where(
                    ExternalBudgetReservation.provider == provider.strip().lower(),
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

    async def usage_by_operation(self, provider: str) -> dict[str, int]:
        start, _end = self._month_bounds(datetime.now(UTC))
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(CostEvent.operation, func.sum(CostEvent.units))
                    .where(
                        CostEvent.provider == provider.strip().lower(),
                        CostEvent.created_at >= start,
                    )
                    .group_by(CostEvent.operation)
                )
            ).all()
        return {str(operation): int(units or 0) for operation, units in rows}

    async def available_for_scan(
        self,
        *,
        provider: str,
        requested_units: int,
        daily_remaining: int,
        service: str = "instagram",
    ) -> ScanBudgetAvailability:
        policy = await self.policy(provider, service)
        if policy is None:
            return ScanBudgetAvailability(
                requested_units=requested_units,
                effective_units=0,
                daily_remaining=max(0, daily_remaining),
                monthly_remaining=0,
                provider_balance=None,
                provider_balance_source="UNKNOWN",
                blocking_reasons=("Активная бюджетная политика провайдера не найдена.",),
            )
        used = await self.current_month_usage(provider)
        active = await self.active_month_reservations(provider)
        monthly_remaining = max(0, policy.monthly_hard_limit_units - used - active)
        balance = await self.latest_balance(provider)
        balance_value = balance.credits_remaining if balance is not None else None
        balance_source = balance.source if balance is not None else "UNKNOWN"
        effective = min(
            max(0, requested_units),
            policy.maximum_manual_scan_budget_units,
            max(0, daily_remaining),
            monthly_remaining,
        )
        if balance_value is not None and balance_source in self.CONFIRMED_SOURCES:
            effective = min(effective, balance_value)

        reasons: list[str] = []
        if requested_units <= 0:
            reasons.append("Лимит проверки должен быть положительным.")
        if daily_remaining <= 0:
            reasons.append("Дневной лимит внешних операций исчерпан.")
        if monthly_remaining <= 0:
            reasons.append("Месячный hard limit провайдера исчерпан.")
        if (
            balance_value is not None
            and balance_source in self.CONFIRMED_SOURCES
            and balance_value <= 0
        ):
            reasons.append("Подтверждённый баланс провайдера исчерпан.")
        return ScanBudgetAvailability(
            requested_units=requested_units,
            effective_units=effective,
            daily_remaining=max(0, daily_remaining),
            monthly_remaining=monthly_remaining,
            provider_balance=balance_value,
            provider_balance_source=balance_source,
            blocking_reasons=tuple(reasons),
        )

    async def snapshot(
        self,
        provider: str,
        service: str = "instagram",
    ) -> ProviderBudgetSnapshot | None:
        policy = await self.policy(provider, service)
        if policy is None:
            return None
        now = datetime.now(UTC)
        used = await self.current_month_usage(provider)
        active = await self.active_month_reservations(provider)
        balance = await self.latest_balance(provider)
        burn_7d = await self._average_daily_burn(provider, now - timedelta(days=7), 7)
        burn_30d = await self._average_daily_burn(provider, now - timedelta(days=30), 30)
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        elapsed_days = max(1, now.day)
        projected = round((used / elapsed_days) * days_in_month, 2)
        remaining = balance.credits_remaining if balance is not None else None
        months_remaining = (
            round(remaining / projected, 2)
            if remaining is not None and projected > 0
            else None
        )
        months_at_target = (
            round(remaining / policy.monthly_target_units, 2)
            if remaining is not None and policy.monthly_target_units > 0
            else None
        )
        if used + active >= policy.monthly_hard_limit_units:
            status = "BLOCKED"
        elif (
            months_remaining is not None
            and months_remaining < policy.target_minimum_months
        ):
            status = "LOW_BALANCE"
        elif projected <= policy.monthly_target_units:
            status = "HEALTHY"
        elif projected <= policy.monthly_soft_limit_units:
            status = "WATCH"
        elif projected < policy.monthly_hard_limit_units:
            status = "HIGH"
        else:
            status = "BLOCKED"
        if remaining is None and status != "BLOCKED":
            status = "UNKNOWN"
        return ProviderBudgetSnapshot(
            provider=provider,
            service=service,
            credits_remaining=remaining,
            credits_remaining_source=balance.source if balance is not None else "UNKNOWN",
            used_this_month=used,
            monthly_target=policy.monthly_target_units,
            monthly_soft_limit=policy.monthly_soft_limit_units,
            monthly_hard_limit=policy.monthly_hard_limit_units,
            monthly_remaining=max(0, policy.monthly_hard_limit_units - used - active),
            average_daily_burn_7d=burn_7d,
            average_daily_burn_30d=burn_30d,
            projected_monthly_burn=projected,
            months_remaining=months_remaining,
            months_remaining_at_target=months_at_target,
            budget_status=status,
            usage_by_operation=await self.usage_by_operation(provider),
        )

    async def _average_daily_burn(
        self,
        provider: str,
        start: datetime,
        days: int,
    ) -> float:
        async with self.session_factory() as session:
            value = await session.scalar(
                select(func.coalesce(func.sum(CostEvent.units), 0)).where(
                    CostEvent.provider == provider.strip().lower(),
                    CostEvent.created_at >= start,
                )
            )
        return round(int(value or 0) / days, 2)

    @staticmethod
    def _month_bounds(value: datetime) -> tuple[datetime, datetime]:
        start = value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if value.month == 12:
            end = start.replace(year=value.year + 1, month=1)
        else:
            end = start.replace(month=value.month + 1)
        return start, end
