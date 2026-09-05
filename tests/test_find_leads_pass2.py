"""UI/API regression: find-leads pass2 (explain, advanced, badge)."""

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


def test_find_leads_pass2_markup_and_cache():
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    sw = (PROJECT_ROOT / "app/web/static/sw.js").read_text(encoding="utf-8")

    assert 'class="find-advanced' in radar
    assert "Расширенные настройки и Live" in radar
    assert "find-heat-strip" in radar
    assert "Потенциальных покупателей" in radar or "потенциальных покупателей" in radar
    assert 'data-lead-explain="' in radar
    assert 'data-lead-take="' in radar
    assert 'href="/hot?vertical={{ rv }}&lead_id={{ lead.id }}"' in radar
    assert ">Написать</a>" in radar
    assert 'data-nav-hot-badge' in base
    assert 'id="lead-explain"' in base
    assert "showLeadExplain" in js
    assert "refreshNavHotBadge" in js
    assert "/api/leads/" in js and "explain" in js
    assert ".nav-badge" in css
    assert ".find-advanced" in css
    assert "13.54.0-f5-hot-ops" in base
    assert "13.54.0-f5-hot-ops" in sw
    # safety strings preserved
    assert "Сколько разрешить на эту проверку?" in radar
    assert 'method="post" action="/api/ops/openai-live"' in radar
    assert "Offline-режим" in radar


@pytest.mark.asyncio
async def test_lead_explain_endpoint_is_grounded(session_factory):
    async with session_factory() as session:
        competitor = Competitor(
            handle="demo.shop",
            normalized_handle="demo.shop",
            display_name="Demo Shop",
            website_url="https://instagram.com/demo.shop",
            active=True,
            vertical=Vertical.FURNITURE,
        )
        contact = Contact(
            platform="instagram",
            username="buyer_one",
            normalized_username="buyer_one",
            profile_url="https://instagram.com/buyer_one",
        )
        session.add_all([competitor, contact])
        await session.flush()
        post = Post(
            competitor_id=competitor.id,
            platform_post_id="post_demo_1",
            url="https://instagram.com/reel/ABC123",
            caption="стулья",
        )
        session.add(post)
        await session.flush()
        comment = Comment(
            platform="instagram",
            platform_comment_id="c1",
            post_id=post.id,
            competitor_id=competitor.id,
            contact_id=contact.id,
            text="Нужно 20 стульев для кафе",
        )
        session.add(comment)
        await session.flush()
        lead = Lead(
            contact_id=contact.id,
            comment_id=comment.id,
            competitor_id=competitor.id,
            vertical=Vertical.FURNITURE,
            intent="BUY",
            product_category="CHAIRS",
            lead_score=88,
            ai_reason="Прямой запрос на покупку стульев",
            status=LeadStatus.NEW,
            analysis_details={
                "confidence": 92,
                "buyer_role": "B2B_HORECA",
                "quantity": 20,
                "evidence": ["Прямой вопрос о покупке", "Указано количество 20"],
                "evidence_ids": [101, 102],
                "factors": {
                    "intent_score": 30,
                    "specificity_score": 20,
                    "value_score": 15,
                    "fit_score": 0,
                },
                "risk_flags": [],
            },
        )
        session.add(lead)
        await session.commit()
        lead_id = lead.id

    settings = Settings(
        _env_file=None,
        web_enabled=True,
        instagram_provider="replay",
        web_manager_id=1001,
    )
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        ExternalUsageService(session_factory),
        crm=CRMService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get("/api/leads/999999/explain")
        response = await client.get(f"/api/leads/{lead_id}/explain")
        radar = await client.get("/radar")

    assert missing.status_code == 404
    assert response.status_code == 200
    data = response.json()
    assert data["grounded"] is True
    assert data["lead_id"] == lead_id
    assert data["evidence_ids"] == [101, 102]
    assert "Прямой запрос" in data["reason"]
    assert any(item["key"] == "intent_score" for item in data["contributions"])
    assert radar.status_code == 200
    assert "Найдите новых клиентов" in radar.text
    assert "data-nav-hot-badge" in radar.text
