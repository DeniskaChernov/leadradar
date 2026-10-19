from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CostEvent, MonitorRun, MonitorRunStatus
from app.services.adaptive_monitoring_policy import AdaptiveMonitoringPolicy
from app.services.instagram_monitor import CycleStats
from app.services.provider_credit_budget_service import ProviderCreditBudgetService


class MonitorRunService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], provider_name: str
    ) -> None:
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
        vertical: str | None = None,
    ) -> int:
        budget = await self.budget_service.snapshot(self.primary_provider)
        async with self.session_factory() as session:
            run = MonitorRun(
                trigger=trigger,
                provider=self.provider_name,
                result_tracking_version=1,
                vertical=vertical,
                status=MonitorRunStatus.RUNNING,
                stats_json={},
                requested_credit_budget=requested_credit_budget,
                effective_credit_budget=effective_credit_budget,
                provider_balance_before=(budget.credits_remaining if budget is not None else None),
                monthly_used_before=(budget.used_this_month if budget is not None else None),
                adaptive_policy_version=AdaptiveMonitoringPolicy.VERSION,
                started_at=datetime.now(UTC),
            )
            session.add(run)
            await session.commit()
            return run.id

    async def finish_success(self, run_id: int, stats: CycleStats) -> None:
        ended_at = datetime.now(UTC)
        actual, operations = await self._run_usage(run_id, ended_at=ended_at)
        budget = await self.budget_service.snapshot(self.primary_provider)
        async with self.session_factory() as session:
            await session.execute(
                update(MonitorRun)
                .where(
                    MonitorRun.id == run_id,
                    MonitorRun.status == MonitorRunStatus.RUNNING,
                )
                .values(
                    status=MonitorRunStatus.FAILED if stats.errors else MonitorRunStatus.SUCCESS,
                    error=(
                        f"Ошибки источников: {stats.errors}. Полученные сигналы сохранены."
                        if stats.errors
                        else None
                    ),
                    stats_json=asdict(stats),
                    actual_credits_spent=actual,
                    operations_json=operations,
                    provider_balance_after=budget.credits_remaining if budget is not None else None,
                    monthly_used_after=budget.used_this_month if budget is not None else None,
                    budget_stop_reason=(
                        "SELECTED_SCAN_LIMIT_REACHED" if stats.budget_stops else None
                    ),
                    completed_at=ended_at,
                )
            )
            await session.commit()

    async def finish_failure(
        self, run_id: int, exc: Exception, *, ended_at: datetime | None = None
    ) -> None:
        ended_at = ended_at or datetime.now(UTC)
        actual, operations = await self._run_usage(run_id, ended_at=ended_at)
        budget = await self.budget_service.snapshot(self.primary_provider)
        async with self.session_factory() as session:
            await session.execute(
                update(MonitorRun)
                .where(
                    MonitorRun.id == run_id,
                    MonitorRun.status == MonitorRunStatus.RUNNING,
                )
                .values(
                    status=MonitorRunStatus.FAILED,
                    error=f"{type(exc).__name__}: {str(exc)[:500]}",
                    actual_credits_spent=actual,
                    operations_json=operations,
                    provider_balance_after=budget.credits_remaining if budget is not None else None,
                    monthly_used_after=budget.used_this_month if budget is not None else None,
                    completed_at=ended_at,
                )
            )
            await session.commit()

    async def recover_interrupted_runs(self) -> int:
        """Startup-only recovery; never resume paid operations automatically."""
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            runs = list(
                await session.scalars(
                    select(MonitorRun)
                    .where(
                        MonitorRun.status == MonitorRunStatus.RUNNING,
                        MonitorRun.started_at <= now,
                    )
                    .order_by(MonitorRun.started_at, MonitorRun.id)
                )
            )
        for run in runs:
            await self.finish_failure(
                run.id,
                RuntimeError("Проверка прервана до завершения предыдущего процесса сервера."),
                ended_at=now,
            )
        return len(runs)

    async def _run_usage(self, run_id: int, *, ended_at: datetime) -> tuple[int, dict[str, int]]:
        async with self.session_factory() as session:
            run = await session.get(MonitorRun, run_id)
            if run is None:
                return 0, {}
            # A crashed historical run must not inherit credits from later scans.
            next_start = await session.scalar(
                select(func.min(MonitorRun.started_at)).where(
                    or_(
                        MonitorRun.started_at > run.started_at,
                        (MonitorRun.started_at == run.started_at) & (MonitorRun.id > run.id),
                    ),
                )
            )
            bounds = [
                CostEvent.service == "instagram",
                CostEvent.created_at >= run.started_at,
                # Windows clock resolution can make a committed cost event
                # share the exact completion timestamp. It still belongs here.
                CostEvent.created_at <= ended_at,
            ]
            if next_start is not None:
                next_start = (
                    next_start.replace(tzinfo=UTC) if next_start.tzinfo is None else next_start
                )
                # A later scan's first event must remain outside this scan.
                bounds.append(CostEvent.created_at < next_start)
            rows = (
                await session.execute(
                    select(CostEvent.operation, func.sum(CostEvent.units))
                    .where(*bounds)
                    .group_by(CostEvent.operation)
                )
            ).all()
        operations = {str(operation): int(units or 0) for operation, units in rows}
        return sum(operations.values()), operations
