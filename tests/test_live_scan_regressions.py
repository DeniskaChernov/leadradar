import httpx
import pytest
from sqlalchemy import select

from app.db.models import Comment, ExternalBudgetReservation, ReservationStatus
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.schemas.instagram import InstagramPost
from app.services.contact_service import ContactService
from app.services.usage_service import ExternalUsageService
from tests.conftest import seed_scrapecreators_instagram_policy
from tests.test_spend_semantics_hardening import ExpensiveCommentPageProvider


def post():
    return InstagramPost(
        platform_post_id="live-regression-post",
        competitor="aiko.uz",
        url="https://www.instagram.com/reel/live-regression/",
        comments_count=20,
    )


async def test_live_comment_scan_avoids_unused_reply_expansion(session_factory):
    await seed_scrapecreators_instagram_policy(session_factory)
    requests = []

    def response(request):
        requests.append(request)
        expensive = request.url.params.get("include_replies") != "false"
        return httpx.Response(200, json={
            "credits_charged": 15 if expensive else 1,
            "credits_remaining": 100,
            "comments": [{
                "id": "live-regression-comment", "text": "narxi?",
                "user": {"id": "buyer", "username": "buyer"},
            }],
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    inner = ScrapeCreatorsProvider("test-key", client=client)
    usage = ExternalUsageService(session_factory)
    scan = ScanBudget(default_limit=1)
    provider = BudgetedInstagramProvider(
        inner, usage, enabled=True, daily_limit=100, scan_budget=scan,
    )
    try:
        result = await provider.get_comment_batch(post(), max_pages=1)
        persisted = await ContactService(session_factory).persist_signal(post(), result.comments[0])
        assert persisted.created
        assert len(requests) == 1
        assert scan.used == 1
        assert await usage.used_today("instagram") == 1
        async with session_factory() as session:
            assert await session.scalar(select(Comment.platform_comment_id)) == "live-regression-comment"
            reservation = await session.scalar(select(ExternalBudgetReservation))
            assert reservation.status == ReservationStatus.FINALIZED
            assert reservation.actual_units == 1
    finally:
        await provider.aclose()


@pytest.mark.parametrize("stop", ["monthly_budget", "live_toggle"])
async def test_paid_comment_page_survives_a_block_before_next_page(session_factory, stop):
    await seed_scrapecreators_instagram_policy(
        session_factory, hard=1 if stop == "monthly_budget" else 100, target=1, soft=1,
    )
    inner = ExpensiveCommentPageProvider(credits_per_page=1)
    usage = ExternalUsageService(session_factory)
    provider = BudgetedInstagramProvider(
        inner, usage, enabled=True, daily_limit=100, scan_budget=ScanBudget(5),
        live_gate=lambda: stop != "live_toggle" or inner.calls == 0,
    )
    result = await provider.get_comment_batch(post(), max_pages=2)
    assert inner.calls == 1
    assert result.pages_fetched == 1
    assert result.next_cursor == "page-2"
    assert result.coverage_status == "PARTIAL"
    assert [comment.platform_comment_id for comment in result.comments] == ["c-1"]
    persisted = await ContactService(session_factory).persist_signal(post(), result.comments[0])
    assert persisted.created
    assert await usage.used_today("instagram") == 1
