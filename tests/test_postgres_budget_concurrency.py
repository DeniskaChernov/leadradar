"""PostgreSQL-only: advisory lock serializes concurrent budget reserve."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import ExternalBudgetReservation, ProviderBudgetPolicy
from app.db.session import normalize_database_url
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService


@pytest_asyncio.fixture
async def postgres_session_factory():
    """Реальная PostgreSQL БД из DATABASE_URL (CI matrix postgres)."""
    raw = os.environ.get("DATABASE_URL", "")
    if "postgres" not in raw.lower():
        pytest.skip("PostgreSQL DATABASE_URL required for advisory-lock concurrency test")
    engine = create_async_engine(normalize_database_url(raw), pool_size=20, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_monthly_budget_concurrent_workers_cap_exactly(
    postgres_session_factory,
):
    """monthly remaining=10, 20 concurrent reserve(1) → ровно 10 успехов."""
    provider = f"pg-concurrency-{uuid4().hex[:12]}"
    service = "instagram"
    hard = 10

    async with postgres_session_factory() as session:
        session.add(
            ProviderBudgetPolicy(
                provider=provider,
                service=service,
                monthly_target_units=hard,
                monthly_soft_limit_units=hard,
                monthly_hard_limit_units=hard,
                default_scan_budget_units=1,
                maximum_manual_scan_budget_units=50,
                target_minimum_months=6,
                comments_target_units=1,
                discovery_target_units=1,
                enrichment_target_units=0,
                reserve_target_units=1,
                active=True,
            )
        )
        await session.commit()

    usage_a = ExternalUsageService(postgres_session_factory)
    usage_b = ExternalUsageService(postgres_session_factory)

    async def try_reserve(usage: ExternalUsageService):
        try:
            return await usage.reserve_budget(
                service,
                "get_comments",
                daily_limit=1000,
                units=1,
                provider=provider,
                lease_seconds=120,
            )
        except ExternalBudgetExceeded:
            return None

    try:
        results = await asyncio.gather(
            *[try_reserve(usage_a if i % 2 else usage_b) for i in range(20)]
        )
        successful = [item for item in results if item is not None]
        assert len(successful) == hard

        with pytest.raises(ExternalBudgetExceeded, match="Месячный hard limit"):
            await usage_a.reserve_budget(
                service,
                "get_comments",
                daily_limit=1000,
                units=1,
                provider=provider,
            )
    finally:
        async with postgres_session_factory() as session:
            await session.execute(
                delete(ExternalBudgetReservation).where(
                    ExternalBudgetReservation.provider == provider
                )
            )
            policy = await session.scalar(
                select(ProviderBudgetPolicy).where(
                    ProviderBudgetPolicy.provider == provider,
                    ProviderBudgetPolicy.service == service,
                )
            )
            if policy is not None:
                await session.delete(policy)
            await session.commit()
