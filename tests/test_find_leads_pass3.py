"""Find-leads pass3: warm filter, result filters, gated monitor."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import (
    Comment,
    Competitor,
    Contact,
    Lead,
    LeadStatus,
    Post,
    Vertical,
)
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_leads_pass3_markup():
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    wizard = (
        PROJECT_ROOT / "app/web/templates/partials/find_leads_wizard.html"
    ).read_text(encoding="utf-8")
    hot = (PROJECT_ROOT / "app/web/templates/hot.html").read_text(encoding="utf-8")
    leads = (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")

    assert "Тёплые:" in radar or "overview.warm" in radar
    assert 'value="warm"' in radar
    assert "data-find-result-filters" in radar
    assert "data-find-filter-kind" in radar
    assert "data-lead-heat" in radar
    assert "Следить постоянно" in wizard
    assert "monitor_schedule_enabled" in wizard
    assert "{% block heading %}HOT{% endblock %}" in hot
    assert "Новые лиды" not in hot
    assert "КЛИЕНТЫ ·" in leads or "клиентов" in leads or "Воронка" in leads
    assert "enhanceFindLeadsResultFilters" in js
    assert "findLeadsResultsUrl" in js
    assert "kind=warm" in js or "warm" in js
    assert "13.53.0-f1-portfolio" in base


@pytest.mark.asyncio
async def test_warm_kind_and_overview_warm_count(session_factory):
    async with session_factory() as session:
        competitor = Competitor(
            handle="warm.shop",
            normalized_handle="warm.shop",
            display_name="Warm",
            active=True,
            vertical=Vertical.FURNITURE,
        )
        contact_hot = Contact(
            platform="instagram",
            username="hot_buyer",
            normalized_username="hot_buyer",
            profile_url="https://instagram.com/hot_buyer",
        )
        contact_warm = Contact(
            platform="instagram",
            username="warm_buyer",
            normalized_username="warm_buyer",
            profile_url="https://instagram.com/warm_buyer",
        )
        session.add_all([competitor, contact_hot, contact_warm])
        await session.flush()
        post = Post(
            competitor_id=competitor.id,
            platform_post_id="warm_post_1",
            url="https://instagram.com/p/warm1",
            caption="мебель",
        )
        session.add(post)
        await session.flush()
        comments = []
        for idx, contact in enumerate((contact_hot, contact_warm), start=1):
            comment = Comment(
                platform="instagram",
                platform_comment_id=f"warm_c_{idx}",
                post_id=post.id,
                competitor_id=competitor.id,
                contact_id=contact.id,
                text="нужны стулья" if idx == 1 else "интересная мебель",
            )
            session.add(comment)
            comments.append(comment)
        await session.flush()
        session.add(
            Lead(
                contact_id=contact_hot.id,
                comment_id=comments[0].id,
                competitor_id=competitor.id,
                vertical=Vertical.FURNITURE,
                intent="BUY",
                lead_score=85,
                status=LeadStatus.NEW,
                ai_reason="hot",
            )
        )
        session.add(
            Lead(
                contact_id=contact_warm.id,
                comment_id=comments[1].id,
                competitor_id=competitor.id,
                vertical=Vertical.FURNITURE,
                intent="CATALOG",
                lead_score=60,
                status=LeadStatus.NEW,
                ai_reason="warm",
            )
        )
        await session.commit()

    queries = WebQueryService(session_factory, hot_threshold=70)
    overview = await queries.signal_overview(vertical="FURNITURE")
    assert overview["hot"] >= 1
    assert overview["warm"] >= 1

    warm_rows = await queries.signals(kind="warm", vertical="FURNITURE")
    assert warm_rows
    assert all(
        row[4] is not None and 50 <= row[4].lead_score < 70 for row in warm_rows
    )

    settings = Settings(
        _env_file=None,
        web_enabled=True,
        instagram_provider="replay",
        web_manager_id=1001,
    )
    app = build_web_app(
        settings,
        queries,
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        ExternalUsageService(session_factory),
        crm=CRMService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        radar = await client.get("/radar?kind=warm")
    assert radar.status_code == 200
    assert 'value="warm"' in radar.text
    assert "Тёплые" in radar.text
