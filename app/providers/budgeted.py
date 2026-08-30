from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from app.providers.base import (
    InstagramProvider,
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


class LiveCallsDisabledError(ProviderUsageBlockedError):
    """Raised before any real provider request when live traffic is disabled."""


class ScanBudgetExceededError(ProviderUsageBlockedError):
    """Raised before the next live call would exceed the per-scan safety cap."""


@dataclass(slots=True)
class ScanBudget:
    """Shared in-memory budget for one monitoring cycle.

    The primary and fallback providers receive the same instance. That matters because a failed
    ScrapeCreators operation followed by Bright Data must consume two units from the same cap.
    """

    limit: int
    used: int = 0

    def reset(self) -> None:
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
    ) -> None:
        self.inner = inner
        self.usage = usage
        self.enabled = enabled
        self.daily_limit = daily_limit
        self.scan_budget = scan_budget
        self.name = inner.name
        self.credit_budget = ProviderCreditBudgetService(usage.session_factory)

    def begin_cycle(self) -> None:
        if self.scan_budget is not None:
            self.scan_budget.reset()
        self.inner.begin_cycle()

    def set_scan_budget_limit(self, limit: int) -> None:
        if self.scan_budget is not None:
            self.scan_budget.limit = max(0, int(limit))
            self.scan_budget.reset()

    def scan_budget_status(self) -> dict[str, int] | None:
        if self.scan_budget is None:
            return None
        return {
            "limit": self.scan_budget.limit,
            "used": self.scan_budget.used,
            "remaining": self.scan_budget.remaining,
        }

    async def _ensure_enabled(self, *, units: int = 1) -> None:
        if not self.enabled:
            raise LiveCallsDisabledError(
                "Реальные Instagram-запросы выключены. "
                "Включайте их только перед контрольным тестом."
            )
        if self.scan_budget is not None:
            self.scan_budget.assert_available(units)
        try:
            await self.usage.assert_available("instagram", self.daily_limit, units=units)
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
        except Exception:
            await self.usage.finalize_reservation(
                reservation_id, units=1, success=False, details=details
            )
            raise
        confirmed_units = await self._persist_credit_observations()
        actual_units = confirmed_units if confirmed_units is not None else 1
        if self.scan_budget is not None and actual_units == 0:
            self.scan_budget.refund(1)
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
                "Фактическое списание провайдера превысило резерв одной операции. "
                "Проверка остановлена для сверки бюджета."
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
    ) -> CommentFetchResult:
        # We cannot know the exact number of pages before the provider responds. Constrain the
        # provider to the smaller of its requested page limit, the daily remainder and the scan
        # remainder. This guarantees one Reel can never silently consume the whole quota.
        await self._ensure_enabled()
        daily_remaining = (
            await self.usage.snapshot("instagram", self.daily_limit)
        ).remaining
        scan_remaining = self.scan_budget.remaining if self.scan_budget is not None else daily_remaining
        remaining = min(daily_remaining, scan_remaining)
        if remaining <= 0:
            raise ScanBudgetExceededError("На эту проверку больше нет разрешённых внешних операций")

        effective_pages = remaining
        if max_pages is not None:
            effective_pages = min(effective_pages, max(1, int(max_pages)))

        reservation_id = await self._reserve("get_comment_batch", effective_pages)
        await self.usage.mark_call_started(reservation_id)

        try:
            result = await self.inner.get_comment_batch(
                post,
                known_comment_ids=known_comment_ids,
                max_pages=effective_pages,
            )
        except Exception:
            await self.usage.finalize_reservation(
                reservation_id,
                units=effective_pages,
                success=False,
                details={
                    "provider": self.inner.name,
                    "pages": 1,
                    "source_account": post.competitor.strip().lower().lstrip("@"),
                },
            )
            raise

        confirmed_units = await self._persist_credit_observations()
        units = (
            confirmed_units
            if confirmed_units is not None
            else max(1, int(result.pages_fetched or 1))
        )
        if units > remaining:
            # A provider adapter that ignored max_pages is unsafe. Block further work and surface it.
            await self.usage.finalize_reservation(
                reservation_id,
                units=units,
                success=True,
                details={
                    "provider": self.inner.name,
                    "pages": units,
                    "over_budget_adapter": True,
                    "source_account": post.competitor.strip().lower().lstrip("@"),
                },
                unit_source=(
                    "PROVIDER_CONFIRMED" if confirmed_units is not None else "ESTIMATED"
                ),
            )
            raise ScanBudgetExceededError(
                f"Провайдер вернул {units} страниц при разрешённом лимите {remaining}. "
                "Проверка остановлена для защиты квоты."
            )

        if self.scan_budget is not None and units < effective_pages:
            self.scan_budget.refund(effective_pages - units)
        await self.usage.finalize_reservation(
            reservation_id,
            units=units,
            success=True,
            details={
                "provider": self.inner.name,
                "pages": units,
                "source_account": post.competitor.strip().lower().lstrip("@"),
            },
            unit_source=(
                "PROVIDER_CONFIRMED" if confirmed_units is not None else "ESTIMATED"
            ),
        )
        return result

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
