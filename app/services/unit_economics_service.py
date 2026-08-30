"""Database-backed unit economics over the immutable cost ledger."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Competitor,
    CostEvent,
    Deal,
    DealSaleSnapshot,
    DealStatus,
    FxRatePolicy,
    Lead,
    LeadStatus,
    PublicSignal,
)

_MONEY_QUANT = Decimal("0.000001")
_RATIO_QUANT = Decimal("0.01")
_ALLOWED_PERIODS = {1, 7, 30}


@dataclass(frozen=True, slots=True)
class EconomicsBreakdown:
    key: str
    label: str
    events: int
    units: int
    known_spend_usd: Decimal
    unpriced_events: int


@dataclass(frozen=True, slots=True)
class SourceEconomics:
    competitor_id: int | None
    source_name: str
    cost_events: int
    known_spend_usd: Decimal
    unpriced_events: int
    signals_count: int
    commercial_leads_count: int
    leads_count: int
    hot_count: int
    b2b_count: int
    won_count: int
    revenue_uzs: Decimal | None
    cost_per_lead_usd: Decimal | None
    cost_per_hot_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class UnitEconomicsSnapshot:
    days: int
    period_started_at: datetime
    generated_at: datetime
    cost_events: int
    priced_events: int
    unpriced_events: int
    attribution_missing_events: int
    known_spend_usd: Decimal
    cost_coverage_percent: Decimal
    signals_count: int
    commercial_leads_count: int
    leads_count: int
    hot_count: int
    b2b_count: int
    won_count: int
    revenue_uzs: Decimal | None
    sale_snapshot_missing_deals: int
    cogs_missing_deals: int
    fx_missing_facts: int
    cohort_attributed_spend_usd: Decimal
    cost_per_signal_usd: Decimal | None
    cost_per_commercial_signal_usd: Decimal | None
    cost_per_lead_usd: Decimal | None
    cost_per_hot_usd: Decimal | None
    cost_per_b2b_usd: Decimal | None
    cost_per_won_usd: Decimal | None
    gross_profit_uzs: Decimal | None
    gross_margin_ratio: Decimal | None
    roi_ratio: Decimal | None
    roi_status: str
    providers: tuple[EconomicsBreakdown, ...]
    verticals: tuple[EconomicsBreakdown, ...]
    sources: tuple[SourceEconomics, ...]


class UnitEconomicsEngine:
    """Aggregate persisted facts; never infer missing prices, COGS or FX rates."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hot_threshold: int,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def snapshot(self, days: int = 30) -> UnitEconomicsSnapshot:
        if days not in _ALLOWED_PERIODS:
            raise ValueError("Economics period must be one of: 1, 7, 30 days")
        now = datetime.now(UTC)
        started_at = now - timedelta(days=days)
        async with self.session_factory() as session:
            cost_events = list(
                await session.scalars(
                    select(CostEvent)
                    .where(CostEvent.created_at >= started_at)
                    .order_by(CostEvent.created_at)
                )
            )
            period_signals = list(
                await session.scalars(
                    select(PublicSignal).where(PublicSignal.created_at >= started_at)
                )
            )
            period_leads = list(
                await session.scalars(select(Lead).where(Lead.created_at >= started_at))
            )
            cohort_lead_ids = [lead.id for lead in period_leads]
            won_deals = list(
                await session.scalars(
                    select(Deal).where(
                        Deal.status == DealStatus.WON,
                        Deal.won_at.is_not(None),
                        Deal.lead_id.in_(cohort_lead_ids),
                    )
                )
            )
            snapshots = {
                item.deal_id: item
                for item in await session.scalars(
                    select(DealSaleSnapshot).where(
                        DealSaleSnapshot.deal_id.in_([deal.id for deal in won_deals])
                    )
                )
            }
            fx_policies = list(
                await session.scalars(
                    select(FxRatePolicy).order_by(
                        FxRatePolicy.effective_from,
                        FxRatePolicy.id,
                    )
                )
            )
            cohort_cost_events = list(
                await session.scalars(
                    select(CostEvent).where(CostEvent.lead_id.in_(cohort_lead_ids))
                )
            )
            all_leads = {lead.id: lead for lead in await session.scalars(select(Lead))}
            competitors = {
                item.id: item for item in await session.scalars(select(Competitor))
            }

        handles = {
            item.normalized_handle.lower(): item.id for item in competitors.values()
        }
        provider_rows: dict[str, dict[str, Any]] = defaultdict(self._cost_bucket)
        vertical_rows: dict[str, dict[str, Any]] = defaultdict(self._cost_bucket)
        source_cost_rows: dict[int | None, dict[str, Any]] = defaultdict(
            self._cost_bucket
        )
        known_spend = Decimal("0")
        unpriced = 0
        attribution_missing = 0
        for event in cost_events:
            cost = Decimal(event.cost_usd) if event.cost_usd is not None else None
            known_spend += cost or Decimal("0")
            unpriced += int(cost is None)
            self._add_cost(provider_rows[event.provider], event, cost)
            lead = all_leads.get(event.lead_id) if event.lead_id else None
            vertical = getattr(event.vertical, "value", event.vertical) or (
                getattr(lead.vertical, "value", lead.vertical) if lead else None
            )
            self._add_cost(vertical_rows[str(vertical or "UNATTRIBUTED")], event, cost)
            source_id = self._source_id(event, lead, handles)
            attribution_missing += int(source_id is None)
            self._add_cost(source_cost_rows[source_id], event, cost)

        commercial_leads = [lead for lead in period_leads if self._is_commercial(lead)]
        qualified_leads = [
            lead for lead in period_leads if lead.status != LeadStatus.NOT_LEAD
        ]
        hot_leads = [
            lead for lead in qualified_leads if lead.lead_score >= self.hot_threshold
        ]
        b2b_leads = [lead for lead in commercial_leads if self._is_b2b(lead)]
        financials = self._financials(
            won_deals=won_deals,
            snapshots=snapshots,
            cost_events=cohort_cost_events,
            fx_policies=fx_policies,
            generated_at=now,
        )
        costs_complete = bool(cost_events) and unpriced == 0
        source_rows = self._source_rows(
            competitors=competitors,
            signals=period_signals,
            commercial_leads=commercial_leads,
            leads=qualified_leads,
            hot_leads=hot_leads,
            b2b_leads=b2b_leads,
            won_deals=won_deals,
            snapshots=snapshots,
            fx_policies=fx_policies,
            lead_by_id=all_leads,
            cost_rows=source_cost_rows,
        )
        return UnitEconomicsSnapshot(
            days=days,
            period_started_at=started_at,
            generated_at=now,
            cost_events=len(cost_events),
            priced_events=len(cost_events) - unpriced,
            unpriced_events=unpriced,
            attribution_missing_events=attribution_missing,
            known_spend_usd=self._money(known_spend),
            cost_coverage_percent=self._coverage(len(cost_events), unpriced),
            signals_count=len(period_signals),
            commercial_leads_count=len(commercial_leads),
            leads_count=len(qualified_leads),
            hot_count=len(hot_leads),
            b2b_count=len(b2b_leads),
            won_count=len(won_deals),
            revenue_uzs=financials["revenue"],
            sale_snapshot_missing_deals=int(financials["snapshot_missing"]),
            cogs_missing_deals=int(financials["cogs_missing"]),
            fx_missing_facts=int(financials["fx_missing"]),
            cohort_attributed_spend_usd=self._money(
                Decimal(financials["attributed_spend_usd"])
            ),
            cost_per_signal_usd=self._cost_per(known_spend, len(period_signals), costs_complete),
            cost_per_commercial_signal_usd=self._cost_per(
                known_spend, len(commercial_leads), costs_complete
            ),
            cost_per_lead_usd=self._cost_per(
                known_spend, len(qualified_leads), costs_complete
            ),
            cost_per_hot_usd=self._cost_per(known_spend, len(hot_leads), costs_complete),
            cost_per_b2b_usd=self._cost_per(known_spend, len(b2b_leads), costs_complete),
            cost_per_won_usd=self._cost_per(
                Decimal(financials["attributed_spend_usd"]),
                len(won_deals),
                costs_complete
                and bool(cohort_cost_events)
                and int(financials["unpriced_costs"]) == 0,
            ),
            gross_profit_uzs=financials["gross_profit"],
            gross_margin_ratio=financials["gross_margin"],
            roi_ratio=financials["roi"],
            roi_status=self._roi_status(
                cost_events=len(cost_events),
                cohort_cost_events=len(cohort_cost_events),
                unpriced_costs=max(int(financials["unpriced_costs"]), unpriced),
                won_count=len(won_deals),
                snapshot_missing=int(financials["snapshot_missing"]),
                cogs_missing=int(financials["cogs_missing"]),
                fx_missing=int(financials["fx_missing"]),
                roi=financials["roi"],
            ),
            providers=self._breakdowns(provider_rows),
            verticals=self._breakdowns(vertical_rows),
            sources=source_rows,
        )

    def _source_rows(
        self,
        *,
        competitors: dict[int, Competitor],
        signals: list[PublicSignal],
        commercial_leads: list[Lead],
        leads: list[Lead],
        hot_leads: list[Lead],
        b2b_leads: list[Lead],
        won_deals: list[Deal],
        snapshots: dict[int, DealSaleSnapshot],
        fx_policies: list[FxRatePolicy],
        lead_by_id: dict[int, Lead],
        cost_rows: dict[int | None, dict[str, Any]],
    ) -> tuple[SourceEconomics, ...]:
        buckets: dict[int | None, dict[str, Any]] = defaultdict(
            lambda: {
                "signals": 0,
                "commercial": 0,
                "leads": 0,
                "hot": 0,
                "b2b": 0,
                "won": 0,
                "revenue": Decimal("0"),
                "revenue_complete": True,
            }
        )
        for signal in signals:
            buckets[signal.competitor_id]["signals"] += 1
        for lead in commercial_leads:
            buckets[lead.competitor_id]["commercial"] += 1
        for lead in leads:
            buckets[lead.competitor_id]["leads"] += 1
        for lead in hot_leads:
            buckets[lead.competitor_id]["hot"] += 1
        for lead in b2b_leads:
            buckets[lead.competitor_id]["b2b"] += 1
        for deal in won_deals:
            lead = lead_by_id.get(deal.lead_id) if deal.lead_id else None
            source_id = lead.competitor_id if lead else None
            buckets[source_id]["won"] += 1
            snapshot = snapshots.get(deal.id)
            rate = (
                self._rate_at(
                    fx_policies,
                    snapshot.sale_currency,
                    "UZS",
                    deal.won_at or snapshot.created_at,
                )
                if snapshot is not None
                else None
            )
            if snapshot is None or rate is None:
                buckets[source_id]["revenue_complete"] = False
            else:
                buckets[source_id]["revenue"] += Decimal(snapshot.sale_amount) * rate
        for source_id in cost_rows:
            buckets[source_id]

        rows = []
        for source_id, activity in buckets.items():
            costs = cost_rows.get(source_id, self._cost_bucket())
            spend = Decimal(costs["spend"])
            costs_complete = costs["events"] > 0 and costs["unpriced"] == 0
            competitor = competitors.get(source_id) if source_id is not None else None
            rows.append(
                SourceEconomics(
                    competitor_id=source_id,
                    source_name=(
                        f"@{competitor.normalized_handle}"
                        if competitor is not None
                        else "Без атрибуции"
                    ),
                    cost_events=int(costs["events"]),
                    known_spend_usd=self._money(spend),
                    unpriced_events=int(costs["unpriced"]),
                    signals_count=int(activity["signals"]),
                    commercial_leads_count=int(activity["commercial"]),
                    leads_count=int(activity["leads"]),
                    hot_count=int(activity["hot"]),
                    b2b_count=int(activity["b2b"]),
                    won_count=int(activity["won"]),
                    revenue_uzs=(
                        self._money(Decimal(activity["revenue"]))
                        if activity["revenue_complete"]
                        else None
                    ),
                    cost_per_lead_usd=self._cost_per(
                        spend, int(activity["leads"]), costs_complete
                    ),
                    cost_per_hot_usd=self._cost_per(
                        spend, int(activity["hot"]), costs_complete
                    ),
                )
            )
        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    row.revenue_uzs or Decimal("-1"),
                    row.hot_count,
                    row.signals_count,
                ),
                reverse=True,
            )
        )

    @staticmethod
    def _is_commercial(lead: Lead) -> bool:
        details = lead.analysis_details or {}
        if details.get("intelligence_version") == "3.0":
            return details.get("is_commercial") is True
        return lead.status != LeadStatus.NOT_LEAD and lead.lead_score >= 50

    @staticmethod
    def _is_b2b(lead: Lead) -> bool:
        details = lead.analysis_details or {}
        return (details.get("buyer_role") or details.get("v2_buyer_role")) == "B2B_HORECA"

    @staticmethod
    def _source_id(
        event: CostEvent, lead: Lead | None, handles: dict[str, int]
    ) -> int | None:
        if event.competitor_id is not None:
            return event.competitor_id
        if lead is not None:
            return lead.competitor_id
        source = str((event.details_json or {}).get("source_account") or "")
        return handles.get(source.strip().lower().lstrip("@"))

    @staticmethod
    def _cost_bucket() -> dict[str, Any]:
        return {"events": 0, "units": 0, "spend": Decimal("0"), "unpriced": 0}

    @staticmethod
    def _add_cost(bucket: dict[str, Any], event: CostEvent, cost: Decimal | None) -> None:
        bucket["events"] += 1
        bucket["units"] += int(event.units or 0)
        bucket["spend"] += cost or Decimal("0")
        bucket["unpriced"] += int(cost is None)

    @classmethod
    def _breakdowns(
        cls, rows: dict[str, dict[str, Any]]
    ) -> tuple[EconomicsBreakdown, ...]:
        return tuple(
            EconomicsBreakdown(
                key=key,
                label=key.replace("_", " ").title(),
                events=int(value["events"]),
                units=int(value["units"]),
                known_spend_usd=cls._money(Decimal(value["spend"])),
                unpriced_events=int(value["unpriced"]),
            )
            for key, value in sorted(
                rows.items(), key=lambda item: Decimal(item[1]["spend"]), reverse=True
            )
        )

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP)

    @staticmethod
    def _coverage(total: int, unknown: int) -> Decimal:
        if total == 0:
            return Decimal("0.00")
        return (Decimal(total - unknown) * 100 / Decimal(total)).quantize(_RATIO_QUANT)

    @classmethod
    def _cost_per(
        cls, spend: Decimal, denominator: int, costs_complete: bool
    ) -> Decimal | None:
        if not costs_complete or denominator <= 0:
            return None
        return cls._money(spend / Decimal(denominator))

    @classmethod
    def _financials(
        cls,
        *,
        won_deals: list[Deal],
        snapshots: dict[int, DealSaleSnapshot],
        cost_events: list[CostEvent],
        fx_policies: list[FxRatePolicy],
        generated_at: datetime,
    ) -> dict[str, Decimal | int | None]:
        revenue = Decimal("0")
        gross_profit = Decimal("0")
        snapshot_missing = 0
        cogs_missing = 0
        sale_fx_missing = 0
        cogs_fx_missing = 0
        for deal in won_deals:
            snapshot = snapshots.get(deal.id)
            if snapshot is None:
                snapshot_missing += 1
                continue
            at = deal.won_at or snapshot.created_at
            sale_rate = cls._rate_at(
                fx_policies,
                snapshot.sale_currency,
                "UZS",
                at,
            )
            if sale_rate is None:
                sale_fx_missing += 1
                continue
            sale_uzs = Decimal(snapshot.sale_amount) * sale_rate
            revenue += sale_uzs
            if snapshot.cogs is None or not snapshot.catalog_currency:
                cogs_missing += 1
                continue
            cogs_rate = cls._rate_at(
                fx_policies,
                snapshot.catalog_currency,
                "UZS",
                at,
            )
            if cogs_rate is None:
                cogs_fx_missing += 1
                continue
            gross_profit += sale_uzs - (
                Decimal(snapshot.cogs) * Decimal(snapshot.quantity) * cogs_rate
            )

        attributed_spend_usd = Decimal("0")
        attributed_spend_uzs = Decimal("0")
        unpriced_costs = 0
        cost_fx_missing = 0
        for event in cost_events:
            if event.cost_usd is None:
                unpriced_costs += 1
                continue
            cost = Decimal(event.cost_usd)
            attributed_spend_usd += cost
            rate = cls._rate_at(fx_policies, "USD", "UZS", event.created_at or generated_at)
            if rate is None:
                cost_fx_missing += 1
                continue
            attributed_spend_uzs += cost * rate

        revenue_complete = snapshot_missing == 0 and sale_fx_missing == 0
        gross_complete = (
            revenue_complete and cogs_missing == 0 and cogs_fx_missing == 0
        )
        costs_complete = (
            bool(cost_events) and unpriced_costs == 0 and cost_fx_missing == 0
        )
        revenue_value = cls._money(revenue) if revenue_complete else None
        gross_value = cls._money(gross_profit) if gross_complete else None
        gross_margin = (
            (gross_profit / revenue).quantize(Decimal("0.0001"))
            if gross_complete and revenue > 0
            else None
        )
        roi = (
            ((gross_profit - attributed_spend_uzs) / attributed_spend_uzs).quantize(
                Decimal("0.0001")
            )
            if gross_complete and costs_complete and attributed_spend_uzs > 0
            else None
        )
        return {
            "revenue": revenue_value,
            "gross_profit": gross_value,
            "gross_margin": gross_margin,
            "roi": roi,
            "snapshot_missing": snapshot_missing,
            "cogs_missing": cogs_missing,
            "fx_missing": sale_fx_missing + cogs_fx_missing + cost_fx_missing,
            "unpriced_costs": unpriced_costs,
            "attributed_spend_usd": attributed_spend_usd,
        }

    @staticmethod
    def _rate_at(
        policies: list[FxRatePolicy],
        base_currency: str,
        quote_currency: str,
        at: datetime,
    ) -> Decimal | None:
        base = base_currency.strip().upper()
        quote = quote_currency.strip().upper()
        if base == quote:
            return Decimal("1")
        target = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
        matches = [
            policy
            for policy in policies
            if policy.base_currency == base
            and policy.quote_currency == quote
            and (
                policy.effective_from
                if policy.effective_from.tzinfo is not None
                else policy.effective_from.replace(tzinfo=UTC)
            )
            <= target
        ]
        if not matches:
            return None
        selected = max(
            matches,
            key=lambda policy: (
                policy.effective_from
                if policy.effective_from.tzinfo is not None
                else policy.effective_from.replace(tzinfo=UTC),
                policy.id,
            ),
        )
        return Decimal(selected.rate)

    @staticmethod
    def _roi_status(
        *,
        cost_events: int,
        cohort_cost_events: int,
        unpriced_costs: int,
        won_count: int,
        snapshot_missing: int,
        cogs_missing: int,
        fx_missing: int,
        roi: Decimal | None,
    ) -> str:
        if won_count == 0:
            if cost_events == 0 and cohort_cost_events == 0:
                return "ROI недоступен: за период нет записанных cost events."
            return "ROI недоступен: у лидов когорты пока нет WON-сделок."
        if snapshot_missing:
            return "ROI недоступен: у части WON-сделок нет immutable sale snapshot."
        if cost_events == 0 and cohort_cost_events == 0:
            return "ROI недоступен: за период нет записанных cost events."
        if unpriced_costs:
            return "ROI недоступен: не все расходы когорты имеют подтверждённую цену."
        if cogs_missing:
            return "ROI недоступен: у части продаж нет подтверждённого COGS snapshot."
        if not cohort_cost_events:
            return "ROI недоступен: у когорты нет расходов, напрямую связанных с lead."
        if fx_missing:
            return "ROI недоступен: не хватает подтверждённого исторического FX-курса."
        if roi is not None:
            return "ROI рассчитан по complete snapshot, direct lead costs и историческому FX."
        return "ROI недоступен: подтверждённые расходы когорты равны нулю."
