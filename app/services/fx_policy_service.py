from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import FxRatePolicy

_FX_WRITE_LOCK = asyncio.Lock()


class FxPolicyService:
    """Версионированные курсы, подтверждённые менеджером; внешних источников нет."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def set_rate(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        rate: Decimal,
        manager_id: int,
        effective_from: datetime | None = None,
    ) -> FxRatePolicy:
        base = self._currency(base_currency)
        quote = self._currency(quote_currency)
        if base == quote:
            raise ValueError("Для одинаковых валют отдельный курс не нужен")
        if not rate.is_finite() or rate <= 0:
            raise ValueError("Курс должен быть конечным положительным числом")
        effective = effective_from or datetime.now(UTC)
        async with _FX_WRITE_LOCK:
            async with self.session_factory() as session:
                current = await session.scalar(
                    select(FxRatePolicy)
                    .where(
                        FxRatePolicy.base_currency == base,
                        FxRatePolicy.quote_currency == quote,
                        FxRatePolicy.active.is_(True),
                    )
                    .order_by(desc(FxRatePolicy.effective_from))
                    .limit(1)
                )
                if current is not None and current.rate == rate:
                    return current
                await session.execute(
                    update(FxRatePolicy)
                    .where(
                        FxRatePolicy.base_currency == base,
                        FxRatePolicy.quote_currency == quote,
                        FxRatePolicy.active.is_(True),
                    )
                    .values(active=False)
                )
                policy = FxRatePolicy(
                    base_currency=base,
                    quote_currency=quote,
                    rate=rate,
                    effective_from=effective,
                    active=True,
                    manager_telegram_id=manager_id,
                )
                session.add(policy)
                await session.commit()
                await session.refresh(policy)
                return policy

    async def rate_at(
        self,
        base_currency: str,
        quote_currency: str,
        at: datetime,
    ) -> Decimal | None:
        base = self._currency(base_currency)
        quote = self._currency(quote_currency)
        if base == quote:
            return Decimal("1")
        async with self.session_factory() as session:
            value = await session.scalar(
                select(FxRatePolicy.rate)
                .where(
                    FxRatePolicy.base_currency == base,
                    FxRatePolicy.quote_currency == quote,
                    FxRatePolicy.effective_from <= at,
                )
                .order_by(desc(FxRatePolicy.effective_from), desc(FxRatePolicy.id))
                .limit(1)
            )
        return Decimal(value) if value is not None else None

    async def list_active(self) -> list[FxRatePolicy]:
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(FxRatePolicy)
                    .where(FxRatePolicy.active.is_(True))
                    .order_by(FxRatePolicy.base_currency, FxRatePolicy.quote_currency)
                )
            )

    @staticmethod
    def _currency(value: str) -> str:
        currency = value.strip().upper()
        if not currency or len(currency) > 8 or not currency.isalpha():
            raise ValueError("Код валюты должен состоять из 1–8 букв")
        return currency
