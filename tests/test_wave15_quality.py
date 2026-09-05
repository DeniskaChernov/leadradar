import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db.models import InterestEvidence
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.crm_service import CRMService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer


def test_pwa_manifest_exists_and_valid():
    manifest_path = Path("app/web/static/manifest.webmanifest")
    assert manifest_path.is_file()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["name"] == "Lead Radar"
    assert payload["start_url"] == "/"
    assert any(icon["src"].endswith(".png") for icon in payload["icons"])


async def test_pwa_manifest_served(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/static/manifest.webmanifest")
    assert response.status_code == 200
    payload = json.loads(response.text)
    assert payload["display"] == "standalone"


async def test_base_template_links_pwa_manifest(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert 'rel="manifest"' in response.text
    assert "/static/icons/icon.svg" in response.text
    assert "13.52.0-hot-nav" in response.text
    assert 'navigator.serviceWorker.register("/sw.js"' in response.text or "navigator.serviceWorker.register('/sw.js'" in response.text


async def test_pwa_service_worker_served_with_root_scope(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/sw.js")
        offline = await client.get("/static/offline.html")
    assert response.status_code == 200
    assert response.headers.get("service-worker-allowed") == "/"
    assert "leadradar-shell-13.52.0-hot-nav" in response.text
    assert "/static/offline.html" in response.text
    assert offline.status_code == 200
    assert 'data-offline-shell="1"' in offline.text


def test_pwa_service_worker_source_exists():
    path = Path("app/web/static/sw.js")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "CACHE_VERSION" in text
    assert "13.52.0-hot-nav" in text


async def test_dedupe_interest_evidence_keeps_newest(session_factory):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    now = datetime.now(UTC)
    shared = {
        "interest_key": "1:2:INTENT:PRICE",
        "contact_id": 1,
        "public_signal_id": 2,
        "evidence_id": 1,
        "competitor_id": 1,
        "vertical": "FURNITURE",
        "dimension": "INTENT",
        "topic": "PRICE",
        "strength": 50,
        "confidence": 80,
        "half_life_days": 30,
        "expires_at": now + timedelta(days=30),
        "active": True,
    }
    older = InterestEvidence(id=1, observed_at=now - timedelta(days=3), **shared)
    newer = InterestEvidence(id=2, observed_at=now, **shared)
    async with session_factory() as session:
        survivors = await engine._dedupe_interest_evidence(session, [older, newer])
        assert len(survivors) == 1
        assert survivors[shared["interest_key"]].id == 2
        await session.flush()


async def test_recalculate_all_continues_after_single_contact_failure(session_factory, monkeypatch):
    engine = AudienceEngine(session_factory, hot_threshold=70)
    contact_service = ContactService(session_factory)
    signal = await contact_service.persist_signal(make_post(), make_comment("recalc-fail"))
    await LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=engine,
    ).process_signal(signal)

    original = engine.recalculate_contact
    calls: list[int] = []

    async def flaky_recalculate(contact_id: int):
        calls.append(contact_id)
        if contact_id == signal.contact_id:
            raise RuntimeError("simulated recalc failure")
        return await original(contact_id)

    monkeypatch.setattr(engine, "recalculate_contact", flaky_recalculate)
    processed = await engine.recalculate_all()
    assert processed == 0
    assert signal.contact_id in calls


def test_deployment_doc_documents_web_manager_id():
    text = Path("docs/DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "## WEB_MANAGER_ID" in text
    assert "WEB_AUTH_ENABLED=false" in text


def test_changelog_covers_recent_waves():
    text = Path("CHANGELOG.md").read_text(encoding="utf-8")
    assert "wave15" in text
    assert "wave14" in text
    assert "wave12" in text


def test_ci_quality_gates_doc_exists():
    path = Path("docs/CI_QUALITY_GATES.md")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "offline-quality-gate" in text
    assert "ruff check" in text


def test_pull_request_template_exists():
    text = Path(".github/pull_request_template.md").read_text(encoding="utf-8")
    assert "offline-quality-gate" in text
    assert "pytest" in text
