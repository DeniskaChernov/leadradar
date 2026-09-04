from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from app.providers.base import (
    InstagramProvider,
    ProviderCallUncertainError,
    ProviderUsageBlockedError,
)
from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
)
from app.services.provider_credit_budget_service import ProviderCreditBudgetService
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService

T = TypeVar("T")
LiveGate = Callable[[], bool]
LiveRefresh = Callable[[], Awaitable[bool]]


class LiveCallsDisabledError(ProviderUsageBlockedError):
    """Raised before any real provider request when live traffic is disabled."""


class ScanBudgetExceededError(ProviderUsageBlockedError):
    """Raised before the next live call would exceed the per-scan safety cap."""


@dataclass(slots=True)
class ScanBudget:
    """Shared in-memory budget for one monitoring cycle.

    The primary and fallback providers receive the same instance. That matters because a failed
    ScrapeCreators operation followed by Bright Data must consume two units from the same cap.

    Controller assigns current_cycle_limit before each run:
    - explicit manual cap → that value
    - scheduler / None → default_limit
    begin_cycle() only clears used; it never mutates the assigned cycle limit.
    """

    default_limit: int
    current_cycle_limit: int | None = None
    used: int = 0

    def __post_init__(self) -> None:
        self.default_limit = max(0, int(self.default_limit))
        if self.current_cycle_limit is None:
            self.current_cycle_limit = self.default_limit

    @property
    def limit(self) -> int:
        return self.current_cycle_limit if self.current_cycle_limit is not None else self.default_limit

    def reset_usage(self) -> None:
        self.used = 0

    def restore_default_limit(self) -> None:
        """Scheduler path: next cycle uses default_limit, not a prior manual Deep scan."""
        self.current_cycle_limit = self.default_limit
        self.used = 0

    def apply_cycle_limit(self, limit: int) -> None:
        """Explicit manual/API cap for the upcoming cycle only."""
        self.current_cycle_limit = max(0, int(limit))
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def assert_available(self, units: int = 1) -> None:
        if self.limit <= 0:
            raise ScanBudgetExceededError("Лимит внешних запросов на одну проверку установлен в 0")
        if self.used + units > self.limit:
            raise ScanBudgetExceededError(
                f"Лимит одной проверки исчерпан: {self.used}/{self.limit} внешних операций"
            )

    def consume(self, units: int = 1) -> None:
        self.assert_available(units)
        self.used += units

    def refund(self, units: int) -> None:
        self.used = max(0, self.used - max(0, units))

    def record_confirmed_spend(self, *, reserved: int, confirmed: int) -> None:
        """Сверка ScanBudget и PROVIDER_CONFIRMED credits после reserve."""
        safe_reserved = max(0, int(reserved))
        safe_confirmed = max(0, int(confirmed))
        if safe_confirmed > safe_reserved:
            # Overshoot: фиксируем фактический spend (даже сверх cap) и останавливаем цикл выше.
            self.used += safe_confirmed - safe_reserved
        elif safe_confirmed < safe_reserved:
            self.refund(safe_reserved - safe_confirmed)


class BudgetedInstagramProvider(InstagramProvider):
    """Fail-closed wrapper for one live provider.

    It enforces both the durable daily budget and a much smaller per-scan cap. Every provider in a
    fallback chain is wrapped separately but shares one :class:`ScanBudget`, so fallback spending
    cannot hide behind a single logical operation.
    """

    def __init__(
        self,
        inner: InstagramProvider,
        usage: ExternalUsageService,
        *,
        enabled: bool,
        daily_limit: int,
        scan_budget: ScanBudget | None = None,
        live_gate: LiveGate | None = None,
        live_refresh: LiveRefresh | None = None,
    ) -> None:
        self.inner = inner
        self.usage = usage
        self._master_enabled = enabled
        self._live_gate = live_gate
        self._live_refresh = live_refresh
        self.daily_limit = daily_limit
        self.scan_budget = scan_budget
        self.name = inner.name
        self.credit_budget = ProviderCreditBudgetService(usage.session_factory)

    @property
    def enabled(self) -> bool:
        if not self._master_enabled:
            return False
        if self._live_gate is not None:
            return bool(self._live_gate())
        return True

    def begin_cycle(self) -> None:
        if self.scan_budget is not None:
            self.scan_budget.reset_usage()
        self.inner.begin_cycle()

    def set_scan_budget_limit(self, limit: int) -> None:
        if self.scan_budget is not None:
            self.scan_budget.apply_cycle_limit(limit)

    def restore_default_scan_budget(self) -> None:
        if self.scan_budget is not None:
            self.scan_budget.restore_default_limit()

    def scan_budget_status(self) -> dict[str, int] | None:
        if self.scan_budget is None:
            return None
        return {
            "limit": self.scan_budget.limit,
            "used": self.scan_budget.used,
            "remaining": self.scan_budget.remaining,
        }

    async def _ensure_enabled(self, *, units: int = 1) -> None:
        # Перед spend всегда сверяем тумблер с БД (не только in-process cache).
        if self._live_refresh is not None:
            armed = await self._live_refresh()
            if not self._master_enabled or not armed:
                raise LiveCallsDisabledError(
                    "Реальные Instagram-запросы выключены. "
                    "Включайте их только перед контрольным тестом."
                )
        elif not self.enabled:
            raise LiveCallsDisabledError(
                "Реальные Instagram-запросы выключены. "
                "Включайте их только перед контрольным тестом."
            )
        if self.scan_budget is not None:
            self.scan_budget.assert_available(units)
        try:
            await self.usage.assert_available(
                "instagram",
                self.daily_limit,
                units=units,
                enforce_daily_limit=False,
            )
        except ExternalBudgetExceeded as exc:
            raise LiveCallsDisabledError(str(exc)) from exc

    async def _reserve(self, operation: str, units: int = 1) -> int:
        await self._ensure_enabled(units=units)
        try:
            reservation_id = await self.usage.reserve_budget(
                "instagram",
                operation,
                self.daily_limit,
                units=units,
                enforce_daily_limit=False,
                provider=self.inner.name,
            )
        except ExternalBudgetExceeded as exc:
            raise LiveCallsDisabledError(str(exc)) from exc
        if self.scan_budget is not None:
            self.scan_budget.consume(units)
        return reservation_id

    async def _call(
        self,
        operation: str,
        call: Callable[[], Awaitable[T]],
        *,
        source_account: str | None = None,
    ) -> T:
        reservation_id = await self._reserve(operation, 1)
        await self.usage.mark_call_started(reservation_id)
        details = {"provider": self.inner.name}
        if source_account:
            details["source_account"] = source_account.strip().lower().lstrip("@")
        try:
            result = await call()
        except Exception as exc:
            await self._settle_failed_call(
                reservation_id,
                reserved_units=1,
                details=details,
                uncertain_reason="external_call_failed_without_provider_credit_observation",
            )
            raise ProviderCallUncertainError(
                "External call failed after delivery started without provider credit proof"
            ) from exc
        confirmed_units = await self._persist_credit_observations()
        actual_units = confirmed_units if confirmed_units is not None else 1
        if self.scan_budget is not None:
            self.scan_budget.record_confirmed_spend(reserved=1, confirmed=actual_units)
        await self.usage.finalize_reservation(
            reservation_id,
            units=actual_units,
            success=True,
            details=details,
            unit_source=(
                "PROVIDER_CONFIRMED" if confirmed_units is not None else "ESTIMATED"
            ),
        )
        if actual_units > 1:
            raise ScanBudgetExceededError(
                f"Фактическое списание провайдера {actual_units} credits при резерве 1. "
                "превысило резерв. Проверка остановлена для сверки бюджета."
            )
        return result

    async def get_profile(self, handle: str) -> InstagramProfile:
        return await self._call(
            "get_profile", lambda: self.inner.get_profile(handle), source_account=handle
        )

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        return await self._call(
            "get_reels", lambda: self.inner.get_reels(handle), source_account=handle
        )

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        return await self._call(
            "get_post",
            lambda: self.inner.get_post(url, competitor),
            source_account=competitor,
        )

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        return (await self.get_comment_batch(post)).comments

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
        cursor: str | None = None,
    ) -> CommentFetchResult:
        """Комменты по одной странице: scan/daily учитывают PROVIDER_CONFIRMED credits, не «страницы»."""
        await self._ensure_enabled()
        page_cap = max(1, int(max_pages)) if max_pages is not None else None
        source_account = post.competitor.strip().lower().lstrip("@")

        all_comments: list[InstagramComment] = []
        seen_ids: set[str] = set()
        pages_fetched = 0
        cursor_exhausted = False
        stopped_on_known = False
        coverage = "UNKNOWN"
        page_cursor = cursor
        provider_name = self.inner.name

        while page_cap is None or pages_fetched < page_cap:
            remaining_before = self.scan_budget.remaining if self.scan_budget is not None else 1
            if remaining_before <= 0:
                if pages_fetched == 0:
                    raise ScanBudgetExceededError(
                        "На эту проверку больше нет разрешённых внешних операций"
                    )
                break

            reservation_id = await self._reserve("get_comment_batch", 1)
            await self.usage.mark_call_started(reservation_id)
            details = {
                "provider": self.inner.name,
                "reserved_pages": 1,
                "source_account": source_account,
                "page_index": pages_fetched + 1,
            }
            try:
                result = await self.inner.get_comment_batch(
                    post,
                    known_comment_ids=known_comment_ids,
                    max_pages=1,
                    cursor=page_cursor,
                )
            except Exception as exc:
                await self._settle_failed_call(
                    reservation_id,
                    reserved_units=1,
                    details=details,
                    uncertain_reason="comment_batch_failed_without_provider_credit_observation",
                )
                raise ProviderCallUncertainError(
                    "Comment batch failed after delivery started without provider credit proof"
                ) from exc

            confirmed_units = await self._persist_credit_observations()
            units = (
                confirmed_units
                if confirmed_units is not None
                else max(1, int(result.pages_fetched or 1))
            )
            if self.scan_budget is not None:
                self.scan_budget.record_confirmed_spend(reserved=1, confirmed=units)
            await self.usage.finalize_reservation(
                reservation_id,
                units=units,
                success=True,
                details={
                    **details,
                    "credits": units,
                    "pages_fetched": int(result.pages_fetched or 1),
                    "over_budget_adapter": units > remaining_before,
                },
                unit_source=(
                    "PROVIDER_CONFIRMED" if confirmed_units is not None else "ESTIMATED"
                ),
            )

            pages_fetched += max(1, int(result.pages_fetched or 1))
            provider_name = result.provider or provider_name
            coverage = result.coverage_status or coverage
            cursor_exhausted = bool(result.cursor_exhausted)
            stopped_on_known = stopped_on_known or bool(result.stopped_on_known_comment)
            for comment in result.comments:
                if comment.platform_comment_id in seen_ids:
                    continue
                seen_ids.add(comment.platform_comment_id)
                all_comments.append(comment)

            if units > remaining_before:
                raise ScanBudgetExceededError(
                    f"Провайдер списал {units} credits при остатке scan {remaining_before}. "
                    "Проверка остановлена для защиты квоты."
                )

            if stopped_on_known or cursor_exhausted or not result.next_cursor:
                page_cursor = None
                break
            page_cursor = result.next_cursor

        if pages_fetched == 0:
            raise ScanBudgetExceededError("На эту проверку больше нет разрешённых внешних операций")

        return CommentFetchResult(
            comments=all_comments,
            provider=provider_name,
            pages_fetched=pages_fetched,
            coverage_status=coverage,
            cursor_exhausted=cursor_exhausted,
            stopped_on_known_comment=stopped_on_known,
            next_cursor=page_cursor,
        )

    async def _settle_failed_call(
        self,
        reservation_id: int,
        *,
        reserved_units: int,
        details: dict,
        uncertain_reason: str,
    ) -> None:
        """Списать подтверждённые credits и очистить leftover observations.

        Без credit proof резервация остаётся UNCERTAIN — charge не выдумывается.
        """
        confirmed_units = await self._persist_credit_observations()
        if confirmed_units is None:
            await self.usage.mark_reservation_uncertain(
                reservation_id,
                reason=uncertain_reason,
                details=details,
            )
            return
        if self.scan_budget is not None:
            self.scan_budget.record_confirmed_spend(
                reserved=reserved_units,
                confirmed=confirmed_units,
            )
        await self.usage.finalize_reservation(
            reservation_id,
            units=confirmed_units,
            success=False,
            details={**details, "failed_after_provider_credit": True},
            unit_source="PROVIDER_CONFIRMED",
        )

    async def _persist_credit_observations(self) -> int | None:
        observations = self.inner.pop_credit_observations()
        confirmed_charges: list[int] = []
        for observation in observations:
            await self.credit_budget.record_credit_snapshot(
                idempotency_key=observation.idempotency_key,
                provider=observation.provider,
                operation=observation.operation,
                source="API_RESPONSE",
                credits_remaining=observation.credits_remaining,
                credits_charged=observation.credits_charged,
            )
            if observation.credits_charged is not None:
                confirmed_charges.append(observation.credits_charged)
        return sum(confirmed_charges) if confirmed_charges else None

    async def aclose(self) -> None:
        await self.inner.aclose()
