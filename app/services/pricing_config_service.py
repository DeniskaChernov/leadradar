from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import PricingConfig

VALID_PRICING_BASES = {"REQUEST", "UNIT", "TOKENS"}


class PricingConfigService:
    """Versioned provider prices; missing prices stay unknown instead of becoming fake zeroes."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def set_price(
        self,
        *,
        provider: str,
        operation: str,
        pricing_basis: str,
        model_name: str | None = None,
        input_price: Decimal | None = None,
        output_price: Decimal | None = None,
        unit_price: Decimal | None = None,
        effective_from: datetime | None = None,
    ) -> PricingConfig:
        basis = pricing_basis.strip().upper()
        if basis not in VALID_PRICING_BASES:
            raise ValueError(f"Unsupported pricing basis: {pricing_basis}")
        if basis == "TOKENS" and input_price is None and output_price is None:
            raise ValueError("Token pricing requires input_price or output_price")
        if basis in {"REQUEST", "UNIT"} and unit_price is None:
            raise ValueError(f"{basis} pricing requires unit_price")
        provider_key = provider.strip().lower()
        operation_key = operation.strip().lower()
        if not provider_key or not operation_key:
            raise ValueError("Provider и operation обязательны")
        model_key = model_name.strip().lower() if model_name else ""
        effective = effective_from or datetime.now(UTC)
        async with self.session_factory() as session:
            await session.execute(
                update(PricingConfig)
                .where(
                    PricingConfig.provider == provider_key,
                    PricingConfig.operation == operation_key,
                    PricingConfig.model_name == model_key,
                    PricingConfig.active.is_(True),
                )
                .values(active=False)
            )
            config = PricingConfig(
                provider=provider_key,
                operation=operation_key,
                model_name=model_key,
                pricing_basis=basis,
                input_price=input_price,
                output_price=output_price,
                unit_price=unit_price,
                effective_from=effective,
                active=True,
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)
            return config

    async def active_price(
        self, provider: str, operation: str, *, model_name: str | None = None
    ) -> PricingConfig | None:
        now = datetime.now(UTC)
        provider_key = provider.strip().lower()
        operation_key = operation.strip().lower()
        model_key = model_name.strip().lower() if model_name else ""
        async with self.session_factory() as session:
            return await session.scalar(
                select(PricingConfig)
                .where(
                    PricingConfig.provider == provider_key,
                    PricingConfig.operation == operation_key,
                    PricingConfig.model_name == model_key,
                    PricingConfig.active.is_(True),
                    PricingConfig.effective_from <= now,
                )
                .order_by(desc(PricingConfig.effective_from))
                .limit(1)
            )

    async def list_active(self) -> list[PricingConfig]:
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(PricingConfig)
                    .where(PricingConfig.active.is_(True))
                    .order_by(PricingConfig.provider, PricingConfig.operation)
                )
            )
