"""Authoritative controlled-pilot readiness (fail-closed, no live API)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, normalize_instagram_handle
from app.db.models import Competitor
from app.services.competitor_freshness_service import (
    FRESHNESS_UNKNOWN,
    CompetitorFreshnessService,
)
from app.services.deployment_readiness_service import (
    OfflineReadinessState,
    inspect_offline_readiness,
)
from app.services.provider_credit_budget_service import ProviderCreditBudgetService

PILOT_PROVIDER = "scrapecreators"
PILOT_SERVICE = "instagram"
REQUIRED_MONTHLY_TARGET = 3000
REQUIRED_MONTHLY_SOFT = 3500
REQUIRED_MONTHLY_HARD = 3800
MIN_PILOT_CREDITS = 1
MAX_PILOT_CREDITS = 10


@dataclass(frozen=True, slots=True)
class PilotReadinessResult:
    ready: bool
    blocking_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    snapshot: dict[str, Any] = field(default_factory=dict)


class PilotReadinessService:
    """Единый fail-closed verdict перед controlled live pilot."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.budget = ProviderCreditBudgetService(session_factory)
        self.freshness = CompetitorFreshnessService(session_factory)

    async def evaluate(
        self,
        *,
        competitor_handle: str | None,
        scan_credits: int,
        offline: OfflineReadinessState | None = None,
        require_single_active: bool = False,
    ) -> PilotReadinessResult:
        blocks: list[str] = []
        warnings: list[str] = []
        offline_state = offline or await inspect_offline_readiness(self.settings)

        if not offline_state.database_healthy:
            blocks.append(
                f"Offline DB readiness false: {offline_state.database_error or 'db unhealthy'}"
            )
        if not offline_state.migration_at_head:
            blocks.append(
                "Alembic not at head: "
                f"{offline_state.migration_error or 'unknown revision'}"
            )
        if not offline_state.migration_drift_free:
            blocks.append(
                "Alembic drift detected: "
                f"{offline_state.migration_error or 'alembic check failed'}"
            )
        if not offline_state.backup_present:
            blocks.append("Backup отсутствует")
        if offline_state.uncertain_reservations > 0:
            blocks.append(
                f"Unresolved UNCERTAIN reservations: {offline_state.uncertain_reservations}"
            )

        policy = await self.budget.policy(PILOT_PROVIDER, PILOT_SERVICE)
        if policy is None:
            blocks.append(
                f"Active ProviderBudgetPolicy missing for {PILOT_PROVIDER}/{PILOT_SERVICE}"
            )
        else:
            if (
                policy.monthly_target_units != REQUIRED_MONTHLY_TARGET
                or policy.monthly_soft_limit_units != REQUIRED_MONTHLY_SOFT
                or policy.monthly_hard_limit_units != REQUIRED_MONTHLY_HARD
            ):
                blocks.append(
                    "Budget policy mismatch: expected "
                    f"target={REQUIRED_MONTHLY_TARGET} soft={REQUIRED_MONTHLY_SOFT} "
                    f"hard={REQUIRED_MONTHLY_HARD}, got target={policy.monthly_target_units} "
                    f"soft={policy.monthly_soft_limit_units} hard={policy.monthly_hard_limit_units}"
                )

        wallet = await self.budget.snapshot(provider=PILOT_PROVIDER, service=PILOT_SERVICE)
        if wallet is None:
            blocks.append("Wallet snapshot недоступен")
        else:
            if wallet.monthly_remaining < scan_credits:
                blocks.append(
                    f"monthly_remaining={wallet.monthly_remaining} < scan cap={scan_credits}"
                )
            if (
                wallet.credits_remaining is not None
                and wallet.credits_remaining_source
                in ProviderCreditBudgetService.CONFIRMED_SOURCES
                and wallet.credits_remaining < scan_credits
            ):
                blocks.append(
                    f"Confirmed provider balance={wallet.credits_remaining} < scan cap={scan_credits}"
                )

        if self.settings.monitor_schedule_enabled:
            blocks.append("MONITOR_SCHEDULE_ENABLED must be false for controlled pilot")
        if not self.settings.instagram_manual_live_scan_only:
            blocks.append("INSTAGRAM_MANUAL_LIVE_SCAN_ONLY must be true for controlled pilot")

        if scan_credits <= 0:
            blocks.append("Scan cap must be > 0")
        elif scan_credits > MAX_PILOT_CREDITS:
            blocks.append(
                f"Scan cap {scan_credits} > {MAX_PILOT_CREDITS} for controlled pilot"
            )
        elif scan_credits < MIN_PILOT_CREDITS:
            blocks.append(f"Scan cap must be >= {MIN_PILOT_CREDITS}")

        if self.settings.meta_ads_live_calls_enabled or self.settings.meta_ads_live_enabled:
            blocks.append("Meta live/spend activation must stay OFF")

        competitor: Competitor | None = None
        active_handles: list[str] = []
        normalized = ""
        if not (competitor_handle or "").strip():
            blocks.append("Не выбран competitor для controlled pilot")
        else:
            normalized = normalize_instagram_handle(competitor_handle or "")
            async with self.session_factory() as session:
                competitor = await session.scalar(
                    select(Competitor).where(Competitor.normalized_handle == normalized)
                )
                active_handles = list(
                    await session.scalars(
                        select(Competitor.normalized_handle)
                        .where(Competitor.active.is_(True))
                        .order_by(Competitor.normalized_handle)
                    )
                )
            if competitor is None:
                blocks.append(f"Competitor @{normalized} отсутствует в DB")
            else:
                competitor = await self.freshness.refresh_competitor(competitor.id)
                if not CompetitorFreshnessService.is_pilot_approved(competitor):
                    status = competitor.freshness_status or FRESHNESS_UNKNOWN
                    blocks.append(
                        f"Competitor @{normalized} freshness not approved "
                        f"(status={status}; reason={competitor.freshness_reason or 'n/a'})"
                    )
                if require_single_active:
                    if active_handles != [normalized]:
                        blocks.append(
                            "Active competitors после arming должен быть ровно 1 "
                            f"(@{normalized}); сейчас={active_handles or []}"
                        )
                elif len(active_handles) > 1:
                    warnings.append(
                        f"Сейчас active={len(active_handles)}; arm должен оставить только @{normalized}"
                    )

        # Неожиданный automatic expansion: live+unlocked без manual-only.
        if (
            self.settings.instagram_live_enabled
            and self.settings.external_spend_unlocked
            and not self.settings.instagram_manual_live_scan_only
        ):
            blocks.append(
                "Конфигурация допускает automatic external expansion "
                "(live ON without INSTAGRAM_MANUAL_LIVE_SCAN_ONLY)"
            )

        snapshot = {
            "competitor": normalized or None,
            "scan_credits": scan_credits,
            "offline_ready": offline_state.ready,
            "backup_present": offline_state.backup_present,
            "uncertain_reservations": offline_state.uncertain_reservations,
            "policy_present": policy is not None,
            "wallet_present": wallet is not None,
            "monthly_remaining": wallet.monthly_remaining if wallet else None,
            "credits_remaining": wallet.credits_remaining if wallet else None,
            "credits_remaining_source": (
                wallet.credits_remaining_source if wallet else None
            ),
            "active_handles": active_handles,
            "freshness_status": competitor.freshness_status if competitor else None,
            "freshness_reason": competitor.freshness_reason if competitor else None,
            "manual_freshness_confirmed_at": (
                competitor.manual_freshness_confirmed_at.isoformat()
                if competitor and competitor.manual_freshness_confirmed_at
                else None
            ),
            "monitor_schedule_enabled": self.settings.monitor_schedule_enabled,
            "instagram_manual_live_scan_only": self.settings.instagram_manual_live_scan_only,
            "meta_ads_live_enabled": self.settings.meta_ads_live_enabled,
            "radar_live_master": self.settings.instagram_live_enabled,
            "openai_live_master": self.settings.openai_live_enabled,
            "external_spend_unlocked": self.settings.external_spend_unlocked,
        }
        # Deduplicate while preserving order
        unique_blocks = tuple(dict.fromkeys(blocks))
        unique_warnings = tuple(dict.fromkeys(warnings))
        return PilotReadinessResult(
            ready=not unique_blocks,
            blocking_reasons=unique_blocks,
            warnings=unique_warnings,
            snapshot=snapshot,
        )
