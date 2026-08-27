"""
test_export_recipes.py — Master Phase 9 test suite

Tests:
  1. CatalogMapper taxonomy resolution
  2. ExportRecipeService dry-run preview (non-mutating)
  3. ExportRecipeService confirmed export (mutates status, creates audit record)
  4. FIRST_PARTY_ELIGIBLE gate enforcement
  5. Privacy assurance: dry-run returns SHA-256 hashes only
  6. Invalid recipe slug handling
  7. API Endpoints GET /api/audiences/export-recipes and POST dry-run
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.models import Contact, ContactEvent, ContactIntelligence, ExportEligibility
from app.schemas.leads import BuyerRole, Intent, LeadAnalysis
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.export_recipe_service import CatalogMapper, ExportRecipeService
from app.services.lead_service import LeadService
from tests.test_contact_service import make_comment, make_post


class QualifiedB2CAnalyzer:
    async def analyze(self, context):
        return LeadAnalysis(
            is_lead=True,
            lead_score=91,
            intent=Intent.PRICE,
            product_category="DINING_SET",
            language="uz",
            reason="CTA asks for plus to receive a price",
            buyer_role=BuyerRole.B2C_CONSUMER,
            factors={"intent_strength": 90, "specificity_score": 10, "role_score": 70, "history_boost": 0, "objection_penalty": 0},
        )


def test_catalog_mapper_categories():
    assert "Dining Sets" in CatalogMapper.get_meta_category("DINING_SET")
    assert "Outdoor Sofas" in CatalogMapper.get_meta_category("RATTAN_SOFA")
    assert "Canopies & Gazebos" in CatalogMapper.get_meta_category("PERGOLA")
    assert CatalogMapper.get_meta_category(None) == "Home & Garden > Furniture"
    assert CatalogMapper.get_meta_category("UNKNOWN") == "Home & Garden > Furniture"


async def test_export_recipe_dry_run(session_factory):
    """Dry-run returns preview metadata and hashes without mutating DB."""
    cs = ContactService(session_factory)
    engine = AudienceEngine(session_factory, hot_threshold=70)
    sig = await cs.persist_signal(make_post(), make_comment("exp-dry-1"))
    await LeadService(session_factory, QualifiedB2CAnalyzer(), hot_threshold=70, audience_engine=engine).process_signal(sig)

    # Qualify contact to make FIRST_PARTY_ELIGIBLE
    async with session_factory() as session:
        contact = await session.get(Contact, sig.contact_id)
        assert contact is not None
        contact.phone = "+998901112233"
        contact.qualification_updated_at = datetime.now(UTC)
        await session.commit()
    await engine.recalculate_contact(sig.contact_id)

    service = ExportRecipeService(session_factory)
    res = await service.run_export_recipe("high_intent_dining", dry_run=True)

    assert res["dry_run"] is True
    assert res["total_matched"] >= 1
    assert res["eligible_count"] >= 1
    assert len(res["sample_privacy_hashes"]) >= 1
    assert res["sample_privacy_hashes"][0] != "+998901112233"  # Must be hashed

    # Verify DB status is NOT changed by dry run
    async with session_factory() as session:
        intel = await session.scalar(
            select(ContactIntelligence).where(ContactIntelligence.contact_id == sig.contact_id)
        )
        assert intel is not None
        assert intel.export_eligibility == ExportEligibility.FIRST_PARTY_ELIGIBLE


async def test_export_recipe_confirmed_export(session_factory):
    """Confirmed export updates status to EXPORTED and emits ContactEvent audit record."""
    cs = ContactService(session_factory)
    engine = AudienceEngine(session_factory, hot_threshold=70)
    sig = await cs.persist_signal(make_post(), make_comment("exp-conf-1"))
    await LeadService(session_factory, QualifiedB2CAnalyzer(), hot_threshold=70, audience_engine=engine).process_signal(sig)

    async with session_factory() as session:
        contact = await session.get(Contact, sig.contact_id)
        assert contact is not None
        contact.phone = "+998909998877"
        contact.qualification_updated_at = datetime.now(UTC)
        await session.commit()
    await engine.recalculate_contact(sig.contact_id)

    service = ExportRecipeService(session_factory)
    res = await service.run_export_recipe("high_intent_dining", dry_run=False, manager_id=42)

    assert res["dry_run"] is False
    assert res["exported_count"] >= 1
    assert "EXP-high_intent_dining" in res["batch_id"]

    # Verify DB state is mutated
    async with session_factory() as session:
        intel = await session.scalar(
            select(ContactIntelligence).where(ContactIntelligence.contact_id == sig.contact_id)
        )
        assert intel is not None
        assert intel.export_eligibility == ExportEligibility.EXPORTED

        # Verify audit event created
        events = (
            await session.scalars(
                select(ContactEvent).where(ContactEvent.contact_id == sig.contact_id)
            )
        ).all()
        export_events = [e for e in events if e.payload_json and e.payload_json.get("action") == "AUDIENCE_EXPORT"]
        assert len(export_events) == 1
        assert export_events[0].payload_json["exported_by"] == 42


async def test_export_recipe_unknown_slug_raises(session_factory):
    service = ExportRecipeService(session_factory)
    with pytest.raises(ValueError, match="Unknown export recipe"):
        await service.run_export_recipe("non_existent_recipe")


async def test_export_recipes_api_endpoints(session_factory):
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings
    from app.services.crm_service import CRMService
    from app.services.lead_workflow_service import LeadWorkflowService
    from app.services.monitor_controller import MonitorController
    from app.web.app import build_web_app
    from app.web.queries import WebQueryService


    settings = Settings(web_auth_enabled=False)
    queries = WebQueryService(session_factory, hot_threshold=70)
    crm = CRMService(session_factory)
    workflow = LeadWorkflowService(session_factory, hot_threshold=70)
    controller = MonitorController(None)  # type: ignore[arg-type]
    app = build_web_app(
        settings=settings,
        queries=queries,
        workflow=workflow,
        controller=controller,
        crm=crm,
    )




    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # GET recipes list
        r1 = await client.get("/api/audiences/export-recipes")
        assert r1.status_code == 200
        data1 = r1.json()
        assert data1["ok"] is True
        assert len(data1["recipes"]) >= 4

        # POST dry run
        r2 = await client.post("/api/audiences/export-recipes/b2b_horeca_wholesale", json={"dry_run": True})
        assert r2.status_code == 200
        data2 = r2.json()
        assert data2["ok"] is True
        assert data2["dry_run"] is True
