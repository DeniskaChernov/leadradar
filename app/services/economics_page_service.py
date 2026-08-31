"""View-model для страницы /economics: wallet, credits-per-outcome и provider breakdown."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import CostEvent, MonitorRun, MonitorRunStatus, ProviderBudgetPolicy
from app.services.provider_credit_budget_service import (
    ProviderBudgetSnapshot,
    ProviderCreditBudgetService,
)
from app.services.unit_economics_service import UnitEconomicsEngine, UnitEconomicsSnapshot

SCRAPECREATORS_PROVIDER = "scrapecreators"
OPENAI_PROVIDER = "openai"
BRIGHTDATA_PROVIDER = "brightdata"

_COMMENT_OPS = frozenset({"get_comment_batch", "get_comments"})
_DISCOVERY_OPS = frozenset({"get_reels", "get_post"})
_PROFILE_OPS = frozenset({"get_profile"})
_ALLOWED_PERIODS = {1, 7, 30}
_RATIO_QUANT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class OperationPlanningRow:
    bucket: str
    label: str
    credits_month: int
    share_percent: Decimal
    planning_target: int
    delta_vs_target: int


@dataclass(frozen=True, slots=True)
class CreditsOutcomeMetrics:
    known_credits: int
    credit_events: int
    credits_per_signal: Decimal | None
    credits_per_commercial_signal: Decimal | None
    credits_per_lead: Decimal | None
    credits_per_hot: Decimal | None
    credits_per_b2b: Decimal | None
    credits_per_won: Decimal | None
    hot_per_1000_credits: Decimal | None
    b2b_per_1000_credits: Decimal | None
    won_per_1000_credits: Decimal | None
    revenue_uzs_per_1000_credits: Decimal | None
    gross_profit_uzs_per_1000_credits: Decimal | None


@dataclass(frozen=True, slots=True)
class ProviderCostSummary:
    provider: str
    label: str
    events: int
    units: int
    input_tokens: int
    output_tokens: int
    known_spend_usd: Decimal
    unpriced_events: int


@dataclass(frozen=True, slots=True)
class EconomicsPageSnapshot:
    days: int
    generated_at: datetime
    provider: ProviderBudgetSnapshot | None
    operation_rows: tuple[OperationPlanningRow, ...]
    credits: CreditsOutcomeMetrics
    usd: UnitEconomicsSnapshot
    openai: ProviderCostSummary
    brightdata: ProviderCostSummary
    infrastructure: ProviderCostSummary
    burn_reasons: tuple[str, ...]


class EconomicsPageService:
    """Собирает economics view-model из существующих ledger-сервисов без внешних вызовов."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hot_threshold: int,
        *,
        scrapecreators_provider: str = SCRAPECREATORS_PROVIDER,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold
        self.scrapecreators_provider = scrapecreators_provider.strip().lower()
        self.budget_service = ProviderCreditBudgetService(session_factory)
        self.unit_economics = UnitEconomicsEngine(session_factory, hot_threshold)

    async def snapshot(self, days: int = 30) -> EconomicsPageSnapshot:
        if days not in _ALLOWED_PERIODS:
            raise ValueError("Economics period must be one of: 1, 7, 30 days")
        now = datetime.now(UTC)
        started_at = now - timedelta(days=days)
        usd = await self.unit_economics.snapshot(days)
        provider = await self.budget_service.snapshot(self.scrapecreators_provider)
        policy = await self.budget_service.policy(self.scrapecreators_provider)
        operation_rows = self._operation_planning_rows(
            provider.usage_by_operation if provider is not None else {},
            policy,
        )
        credits = await self._credits_outcome_metrics(started_at, usd)
        openai, brightdata, infrastructure = await self._provider_summaries(started_at)
        burn_reasons = await self._burn_reasons(provider)
        return EconomicsPageSnapshot(
            days=days,
            generated_at=now,
            provider=provider,
            operation_rows=operation_rows,
            credits=credits,
            usd=usd,
            openai=openai,
            brightdata=brightdata,
            infrastructure=infrastructure,
            burn_reasons=burn_reasons,
        )

    async def _credits_outcome_metrics(
        self,
        started_at: datetime,
        usd: UnitEconomicsSnapshot,
    ) -> CreditsOutcomeMetrics:
        async with self.session_factory() as session:
            events = list(
                await session.scalars(
                    select(CostEvent).where(
                        CostEvent.provider == self.scrapecreators_provider,
                        CostEvent.created_at >= started_at,
                    )
                )
            )
        known_credits = sum(int(event.units or 0) for event in events)
        credits_complete = bool(events)
        return CreditsOutcomeMetrics(
            known_credits=known_credits,
            credit_events=len(events),
            credits_per_signal=self._credits_per(
                known_credits, usd.signals_count, credits_complete
            ),
            credits_per_commercial_signal=self._credits_per(
                known_credits, usd.commercial_leads_count, credits_complete
            ),
            credits_per_lead=self._credits_per(
                known_credits, usd.leads_count, credits_complete
            ),
            credits_per_hot=self._credits_per(known_credits, usd.hot_count, credits_complete),
            credits_per_b2b=self._credits_per(known_credits, usd.b2b_count, credits_complete),
            credits_per_won=self._credits_per(known_credits, usd.won_count, credits_complete),
            hot_per_1000_credits=self._outcome_per_1000_credits(
                usd.hot_count, known_credits, credits_complete
            ),
            b2b_per_1000_credits=self._outcome_per_1000_credits(
                usd.b2b_count, known_credits, credits_complete
            ),
            won_per_1000_credits=self._outcome_per_1000_credits(
                usd.won_count, known_credits, credits_complete
            ),
            revenue_uzs_per_1000_credits=self._money_per_1000_credits(
                usd.revenue_uzs, known_credits, credits_complete
            ),
            gross_profit_uzs_per_1000_credits=self._money_per_1000_credits(
                usd.gross_profit_uzs, known_credits, credits_complete
            ),
        )

    async def _provider_summaries(
        self,
        started_at: datetime,
    ) -> tuple[ProviderCostSummary, ProviderCostSummary, ProviderCostSummary]:
        async with self.session_factory() as session:
            events = list(
                await session.scalars(
                    select(CostEvent).where(CostEvent.created_at >= started_at)
                )
            )
        return (
            self._summarize_provider(events, OPENAI_PROVIDER, "OpenAI"),
            self._summarize_provider(events, BRIGHTDATA_PROVIDER, "Bright Data"),
            self._summarize_infrastructure(events),
        )

    async def _burn_reasons(
        self,
        provider: ProviderBudgetSnapshot | None,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if provider is None:
            return ("Активная бюджетная политика ScrapeCreators не настроена.",)
        if provider.budget_status == "UNKNOWN":
            reasons.append(
                "Баланс пакета не подтверждён: months remaining будет показан только после "
                "API_RESPONSE, BALANCE_ENDPOINT или MANUAL snapshot."
            )
        if (
            provider.months_remaining is not None
            and provider.months_remaining < 6
        ):
            reasons.append(
                f"При текущем прогнозе пакета хватит примерно на {provider.months_remaining} "
                "месяца. Цель — не менее 6 месяцев."
            )
        if provider.projected_monthly_burn > provider.monthly_target:
            reasons.append(
                "Прогноз месяца выше рабочей цели "
                f"({provider.projected_monthly_burn:.0f} > {provider.monthly_target})."
            )
        async with self.session_factory() as session:
            recent_runs = list(
                await session.scalars(
                    select(MonitorRun)
                    .where(
                        MonitorRun.status == MonitorRunStatus.SUCCESS,
                        MonitorRun.completed_at.is_not(None),
                    )
                    .order_by(MonitorRun.completed_at.desc())
                    .limit(5)
                )
            )
        if recent_runs:
            latest = recent_runs[0]
            stats = latest.stats_json or {}
            comment_requests = int(stats.get("comment_requests", 0))
            avoided = int(stats.get("avoided_requests", 0))
            deferred = int(stats.get("budget_deferred_candidates", 0))
            if comment_requests > 0:
                reasons.append(
                    f"Последний Radar: {comment_requests} страниц комментариев, "
                    f"сэкономлено запросов {avoided}."
                )
            if deferred > 0:
                reasons.append(
                    f"Последний Radar отложил {deferred} кандидатов из-за scan budget."
                )
        comments_used = sum(
            credits
            for operation, credits in (provider.usage_by_operation or {}).items()
            if self._bucket_for_operation(SCRAPECREATORS_PROVIDER, operation, {}) == "comments"
        )
        if comments_used > 0 and provider.monthly_target > 0:
            comments_share = (comments_used / provider.monthly_target) * 100
            if comments_share >= 50:
                reasons.append(
                    f"Comments refresh занимает ~{comments_share:.0f}% от рабочей цели месяца."
                )
        if not reasons:
            reasons.append("Расход в пределах плановых ориентиров.")
        return tuple(reasons)

    @classmethod
    def _operation_planning_rows(
        cls,
        usage_by_operation: dict[str, int],
        policy: ProviderBudgetPolicy | None,
    ) -> tuple[OperationPlanningRow, ...]:
        bucket_totals: dict[str, int] = {
            "comments": 0,
            "discovery": 0,
            "profiles": 0,
            "fallback_retry": 0,
            "other": 0,
        }
        for operation, credits in usage_by_operation.items():
            bucket = cls._bucket_for_operation(SCRAPECREATORS_PROVIDER, operation, {})
            bucket_totals[bucket] += int(credits or 0)
        total = sum(bucket_totals.values())
        targets = {
            "comments": policy.comments_target_units if policy is not None else 0,
            "discovery": policy.discovery_target_units if policy is not None else 0,
            "profiles": policy.enrichment_target_units if policy is not None else 0,
            "fallback_retry": policy.reserve_target_units if policy is not None else 0,
            "other": 0,
        }
        labels = {
            "comments": "Comments",
            "discovery": "Discovery",
            "profiles": "Profiles",
            "fallback_retry": "Fallback / Retry",
            "other": "Other",
        }
        rows: list[OperationPlanningRow] = []
        for bucket in ("comments", "discovery", "profiles", "fallback_retry", "other"):
            credits = bucket_totals[bucket]
            share = (
                (Decimal(credits) * 100 / Decimal(total)).quantize(_RATIO_QUANT)
                if total > 0
                else Decimal("0.00")
            )
            target = targets[bucket]
            rows.append(
                OperationPlanningRow(
                    bucket=bucket,
                    label=labels[bucket],
                    credits_month=credits,
                    share_percent=share,
                    planning_target=target,
                    delta_vs_target=credits - target,
                )
            )
        return tuple(rows)

    @staticmethod
    def _bucket_for_operation(provider: str, operation: str, details: dict) -> str:
        normalized_provider = provider.strip().lower()
        normalized_operation = operation.strip().lower()
        if normalized_provider == BRIGHTDATA_PROVIDER or details.get("fallback_provider"):
            return "fallback_retry"
        if normalized_operation in _COMMENT_OPS or "comment" in normalized_operation:
            return "comments"
        if normalized_operation in _DISCOVERY_OPS or "reel" in normalized_operation:
            return "discovery"
        if normalized_operation in _PROFILE_OPS or "profile" in normalized_operation:
            return "profiles"
        if "retry" in normalized_operation or "fallback" in normalized_operation:
            return "fallback_retry"
        return "other"

    @classmethod
    def _summarize_events(
        cls,
        events: list[CostEvent],
        provider_key: str,
        label: str,
    ) -> ProviderCostSummary:
        known_spend = Decimal("0")
        unpriced = 0
        input_tokens = 0
        output_tokens = 0
        units = 0
        for event in events:
            units += int(event.units or 0)
            if event.input_tokens is not None:
                input_tokens += int(event.input_tokens)
            if event.output_tokens is not None:
                output_tokens += int(event.output_tokens)
            if event.cost_usd is None:
                unpriced += 1
            else:
                known_spend += Decimal(event.cost_usd)
        return ProviderCostSummary(
            provider=provider_key,
            label=label,
            events=len(events),
            units=units,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            known_spend_usd=known_spend.quantize(Decimal("0.000001")),
            unpriced_events=unpriced,
        )

    @classmethod
    def _summarize_provider(
        cls,
        events: list[CostEvent],
        provider: str,
        label: str,
    ) -> ProviderCostSummary:
        selected = [event for event in events if event.provider == provider]
        return cls._summarize_events(selected, provider, label)

    @classmethod
    def _summarize_infrastructure(cls, events: list[CostEvent]) -> ProviderCostSummary:
        infra_providers = {"hosting", "storage", "infrastructure", "infra"}
        selected = [
            event
            for event in events
            if event.provider.strip().lower() in infra_providers
            or str((event.details_json or {}).get("category") or "").lower()
            == "infrastructure"
        ]
        return cls._summarize_events(selected, "infrastructure", "Infrastructure")

    @staticmethod
    def _credits_per(
        credits: int,
        denominator: int,
        credits_complete: bool,
    ) -> Decimal | None:
        if not credits_complete or denominator <= 0:
            return None
        return (Decimal(credits) / Decimal(denominator)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @staticmethod
    def _outcome_per_1000_credits(
        count: int,
        credits: int,
        credits_complete: bool,
    ) -> Decimal | None:
        if not credits_complete or credits <= 0:
            return None
        return (Decimal(count) * 1000 / Decimal(credits)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @staticmethod
    def _money_per_1000_credits(
        amount: Decimal | None,
        credits: int,
        credits_complete: bool,
    ) -> Decimal | None:
        if not credits_complete or credits <= 0 or amount is None:
            return None
        return (amount * 1000 / Decimal(credits)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
