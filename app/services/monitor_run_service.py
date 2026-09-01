from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CostEvent, MonitorRun, MonitorRunStatus
from app.services.adaptive_monitoring_policy import AdaptiveMonitoringPolicy
from app.services.instagram_monitor import CycleStats
from app.services.provider_credit_budget_service import ProviderCreditBudgetService


class MonitorRunService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], provider_name: str) -> None:
        self.session_factory = session_factory
        self.provider_name = provider_name
        self.primary_provider = provider_name.split("+", maxsplit=1)[0]
        self.budget_service = ProviderCreditBudgetService(session_factory)

    async def start(
        self,
        trigger: str,
        *,
        requested_credit_budget: int | None = None,
        effective_credit_budget: int | None = None,
    ) -> int:
        budget = await self.budget_service.snapshot(self.primary_provider)
        async with self.session_factory() as session:
            run = MonitorRun(
                trigger=trigger,
                provider=self.provider_name,
                status=MonitorRunStatus.RUNNING,
                stats_json={},
                requested_credit_budget=requested_credit_budget,
                effective_credit_budget=effective_credit_budget,
                provider_balance_before=(
                    budget.credits_remaining if budget is not None else None
                ),
                monthly_used_before=(
                    budget.used_this_month if budget is not None else None
                ),
                adaptive_policy_version=AdaptiveMonitoringPolicy.VERSION,
                started_at=datetime.now(UTC),
            )
            session.add(run)
            await session.commit()
            return run.id

    async def finish_success(self, run_id: int, stats: CycleStats) -> None:
        actual, operations = await self._run_usage(run_id)
        budget = await self.budget_service.snapshot(self.primary_provider)
        async with self.session_factory() as session:
            run = await session.get(MonitorRun, run_id)
            if run is None:
                return
            run.status = MonitorRunStatus.SUCCESS
            run.stats_json = asdict(stats)
            run.actual_credits_spent = actual
            run.operations_json = operations
            run.provider_balance_after = (
                budget.credits_remaining if budget is not None else None
            )
            run.monthly_used_after = budget.used_this_month if budget is not None else None
            run.budget_stop_reason = (
                "SELECTED_SCAN_LIMIT_REACHED" if stats.budget_stops else None
            )
            run.completed_at = datetime.now(UTC)
            await session.commit()

    async def finish_failure(self, run_id: int, exc: Exception) -> None:
        actual, operations = await self._run_usage(run_id)
        budget = await self.budget_service.snapshot(self.primary_provider)
        async with self.session_factory() as session:
            run = await session.get(MonitorRun, run_id)
            if run is None:
                return
            run.status = MonitorRunStatus.FAILED
            run.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            run.actual_credits_spent = actual
            run.operations_json = operations
            run.provider_balance_after = (
                budget.credits_remaining if budget is not None else None
            )
            run.monthly_used_after = budget.used_this_month if budget is not None else None
            run.completed_at = datetime.now(UTC)
            await session.commit()

    async def _run_usage(self, run_id: int) -> tuple[int, dict[str, int]]:
        async with self.session_factory() as session:
            run = await session.get(MonitorRun, run_id)
            if run is None:
                return 0, {}
            rows = (
                await session.execute(
                    select(CostEvent.operation, func.sum(CostEvent.units))
                    .where(
                        CostEvent.service == "instagram",
                        CostEvent.created_at >= run.started_at,
                    )
                    .group_by(CostEvent.operation)
                )
            ).all()
        operations = {str(operation): int(units or 0) for operation, units in rows}
        return sum(operations.values()), operations
