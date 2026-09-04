"""Hardening: ScanBudget cycle limits and uncertain external failures."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import ExternalBudgetReservation, ReservationStatus
from app.providers.base import ProviderCallUncertainError
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.schemas.instagram import InstagramProfile, ProviderCreditObservation
from app.services.usage_service import ExternalUsageService


class BoomProvider:
    name = "scrapecreators"

    def begin_cycle(self) -> None:
        return None

    def pop_credit_observations(self):
        return []

    async def get_profile(self, handle: str) -> InstagramProfile:
        raise RuntimeError("network down")

    async def get_reels(self, handle: str):
        raise RuntimeError("network down")

    async def get_post(self, url: str, competitor: str):
        raise RuntimeError("network down")

    async def get_comments(self, post):
        raise RuntimeError("network down")

    async def aclose(self) -> None:
        return None


def test_scan_budget_manual_cap_does_not_stick_after_restore():
    budget = ScanBudget(default_limit=10)
    budget.apply_cycle_limit(40)
    assert budget.limit == 40
    budget.consume(2)
    budget.restore_default_limit()
    assert budget.limit == 10
    assert budget.used == 0


def test_scan_budget_begin_cycle_keeps_manual_cap_until_restore():
    budget = ScanBudget(default_limit=10)
    budget.apply_cycle_limit(40)
    budget.reset_usage()
    assert budget.limit == 40
    budget.restore_default_limit()
    assert budget.limit == 10


@pytest.mark.asyncio
async def test_started_external_failure_marks_reservation_uncertain(session_factory):
    from tests.conftest import seed_scrapecreators_instagram_policy

    await seed_scrapecreators_instagram_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    provider = BudgetedInstagramProvider(
        BoomProvider(),
        usage,
        enabled=True,
        daily_limit=100,
        scan_budget=ScanBudget(default_limit=10),
    )

    with pytest.raises(ProviderCallUncertainError):
        await provider.get_profile("aiko.uz")

    async with session_factory() as session:
        reservation = await session.scalar(select(ExternalBudgetReservation))
    assert reservation is not None
    assert reservation.status == ReservationStatus.UNCERTAIN
    assert reservation.call_started_at is not None
    assert reservation.details_json.get("reason")


class ChargedThenBoomProvider:
    name = "scrapecreators"

    def __init__(self) -> None:
        self.calls = 0
        self._credit_observations = []

    def begin_cycle(self) -> None:
        return None

    def pop_credit_observations(self):
        items = self._credit_observations
        self._credit_observations = []
        return items

    async def get_profile(self, handle: str) -> InstagramProfile:
        self.calls += 1
        self._credit_observations.append(
            ProviderCreditObservation(
                idempotency_key=f"profile-{self.calls}",
                provider="scrapecreators",
                operation="get_profile",
                credits_charged=1,
                credits_remaining=10,
            )
        )
        if self.calls == 1:
            raise RuntimeError("parse fail after billed response")
        return InstagramProfile(username=handle, profile_url=f"https://instagram.com/{handle}")

    async def get_reels(self, handle: str):
        raise RuntimeError("unused")

    async def get_post(self, url: str, competitor: str):
        raise RuntimeError("unused")

    async def get_comments(self, post):
        raise RuntimeError("unused")

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_billed_parse_failure_does_not_leak_credits_to_next_call(session_factory):
    from tests.conftest import seed_scrapecreators_instagram_policy

    await seed_scrapecreators_instagram_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    provider = BudgetedInstagramProvider(
        ChargedThenBoomProvider(),
        usage,
        enabled=True,
        daily_limit=100,
        scan_budget=ScanBudget(default_limit=10),
    )

    with pytest.raises(ProviderCallUncertainError):
        await provider.get_profile("aiko.uz")

    profile = await provider.get_profile("aiko.uz")
    assert profile.username == "aiko.uz"

    async with session_factory() as session:
        reservations = list(await session.scalars(select(ExternalBudgetReservation)))
    assert len(reservations) == 2
    assert {item.status for item in reservations} == {ReservationStatus.FINALIZED}
    assert sum(item.actual_units or 0 for item in reservations) == 2


class ExpensiveCommentPageProvider:
    """Одна страница комментариев списывает много credits (как live ScrapeCreators)."""

    name = "scrapecreators"

    def __init__(self, *, credits_per_page: int = 15) -> None:
        self.credits_per_page = credits_per_page
        self.calls = 0
        self._credit_observations: list[ProviderCreditObservation] = []

    def begin_cycle(self) -> None:
        return None

    def pop_credit_observations(self):
        items = self._credit_observations
        self._credit_observations = []
        return items

    async def get_profile(self, handle: str) -> InstagramProfile:
        raise RuntimeError("unused")

    async def get_reels(self, handle: str):
        raise RuntimeError("unused")

    async def get_post(self, url: str, competitor: str):
        raise RuntimeError("unused")

    async def get_comments(self, post):
        raise RuntimeError("unused")

    async def get_comment_batch(
        self,
        post,
        *,
        known_comment_ids=None,
        max_pages=None,
        cursor=None,
    ):
        from app.schemas.instagram import CommentFetchResult, InstagramComment

        self.calls += 1
        self._credit_observations.append(
            ProviderCreditObservation(
                idempotency_key=f"comments-{self.calls}",
                provider="scrapecreators",
                operation="get_comment_page",
                credits_charged=self.credits_per_page,
                credits_remaining=100,
            )
        )
        return CommentFetchResult(
            comments=[
                InstagramComment(
                    platform_comment_id=f"c-{self.calls}",
                    platform_user_id="u1",
                    username="u1",
                    display_name="U1",
                    profile_url="https://instagram.com/u1/",
                    text="narxi?",
                )
            ],
            provider=self.name,
            pages_fetched=1,
            coverage_status="PARTIAL",
            cursor_exhausted=False,
            next_cursor=f"page-{self.calls + 1}",
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_comment_page_credit_overshoot_stops_before_second_page(session_factory):
    """Scan cap в credits: дорогая 1-я страница не даёт уйти во 2-ю."""
    from app.providers.budgeted import ScanBudgetExceededError
    from app.schemas.instagram import InstagramPost
    from tests.conftest import seed_scrapecreators_instagram_policy

    await seed_scrapecreators_instagram_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    inner = ExpensiveCommentPageProvider(credits_per_page=15)
    scan = ScanBudget(default_limit=5)
    provider = BudgetedInstagramProvider(
        inner,
        usage,
        enabled=True,
        daily_limit=100,
        scan_budget=scan,
    )
    post = InstagramPost(
        platform_post_id="p1",
        competitor="aiko.uz",
        url="https://www.instagram.com/reel/test/",
        comments_count=40,
    )

    with pytest.raises(ScanBudgetExceededError, match="15 credits"):
        await provider.get_comment_batch(post, max_pages=2)

    assert inner.calls == 1
    assert scan.used == 15
    assert scan.remaining == 0

    async with session_factory() as session:
        reservations = list(await session.scalars(select(ExternalBudgetReservation)))
    assert len(reservations) == 1
    assert reservations[0].status == ReservationStatus.FINALIZED
    assert reservations[0].actual_units == 15


@pytest.mark.asyncio
async def test_budgeted_comment_batch_fetches_one_page_at_a_time(session_factory):
    """max_pages=2 → два reserve(1); inner всегда видит max_pages=1 + cursor."""
    from app.schemas.instagram import CommentFetchResult, InstagramComment, InstagramPost
    from tests.conftest import seed_scrapecreators_instagram_policy

    class CheapPagingProvider:
        name = "scrapecreators"

        def __init__(self) -> None:
            self.calls = 0
            self.max_pages_seen: list[int | None] = []
            self.cursors_seen: list[str | None] = []
            self._credit_observations: list[ProviderCreditObservation] = []

        def begin_cycle(self) -> None:
            return None

        def pop_credit_observations(self):
            items = self._credit_observations
            self._credit_observations = []
            return items

        async def get_comment_batch(
            self,
            post,
            *,
            known_comment_ids=None,
            max_pages=None,
            cursor=None,
        ):
            self.calls += 1
            self.max_pages_seen.append(max_pages)
            self.cursors_seen.append(cursor)
            self._credit_observations.append(
                ProviderCreditObservation(
                    idempotency_key=f"comments-{self.calls}",
                    provider="scrapecreators",
                    operation="get_comment_page",
                    credits_charged=1,
                    credits_remaining=50,
                )
            )
            if cursor is None:
                return CommentFetchResult(
                    comments=[
                        InstagramComment(
                            platform_comment_id="c1",
                            platform_user_id="u1",
                            username="u1",
                            display_name="U1",
                            profile_url="https://instagram.com/u1/",
                            text="hi",
                        )
                    ],
                    provider=self.name,
                    pages_fetched=1,
                    coverage_status="PARTIAL",
                    cursor_exhausted=False,
                    next_cursor="page-2",
                )
            return CommentFetchResult(
                comments=[
                    InstagramComment(
                        platform_comment_id="c2",
                        platform_user_id="u2",
                        username="u2",
                        display_name="U2",
                        profile_url="https://instagram.com/u2/",
                        text="price?",
                    )
                ],
                provider=self.name,
                pages_fetched=1,
                coverage_status="FULL",
                cursor_exhausted=True,
                next_cursor=None,
            )

        async def aclose(self) -> None:
            return None

    await seed_scrapecreators_instagram_policy(session_factory)
    usage = ExternalUsageService(session_factory)
    inner = CheapPagingProvider()
    scan = ScanBudget(default_limit=5)
    provider = BudgetedInstagramProvider(
        inner,
        usage,
        enabled=True,
        daily_limit=100,
        scan_budget=scan,
    )
    post = InstagramPost(
        platform_post_id="p1",
        competitor="aiko.uz",
        url="https://www.instagram.com/reel/test/",
        comments_count=40,
    )

    result = await provider.get_comment_batch(post, max_pages=2)

    assert inner.calls == 2
    assert inner.max_pages_seen == [1, 1]
    assert inner.cursors_seen == [None, "page-2"]
    assert result.pages_fetched == 2
    assert {c.platform_comment_id for c in result.comments} == {"c1", "c2"}
    assert scan.used == 2
