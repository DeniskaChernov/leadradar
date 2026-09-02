import asyncio
import signal
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import _install_shutdown_handlers
from app.services.crm_service import CRMService
from app.services.independent_quality_gates_service import IndependentQualityGatesService
from app.services.lead_analysis_pipeline import LeadAnalysisPipeline
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from scripts.update_state_notes import _plan_progress, build_state_md


async def test_openai_live_arm_blocked_when_unseen_gates_fail(session_factory, monkeypatch):
    settings = Settings(
        _env_file=None,
        web_enabled=True,
        instagram_provider="replay",
        web_manager_id=1001,
        openai_live_calls_enabled=True,
        external_kill_switch=False,
        external_live_unlock="ALLOW_EXTERNAL_CALLS",
        openai_api_key="test-key",
    )

    class BlockedGatesService:
        def snapshot(self, *, rules_version: str = "3.2"):
            class Snap:
                def openai_live_allowed(self):
                    return False, "Unseen quality gates blocked for test"

            snap = Snap()
            snap.rules_version = rules_version
            return snap

    monkeypatch.setattr("app.web.app.IndependentQualityGatesService", BlockedGatesService)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(None),  # type: ignore[arg-type]
        crm=CRMService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/ops/openai-live", json={"armed": True})
    assert response.status_code == 409
    assert "blocked" in response.json()["detail"].lower() or "unseen" in response.json()["detail"].lower()


def test_unseen_gate_openai_allowed_when_gates_pass():
    snap = IndependentQualityGatesService().snapshot(rules_version="3.2")
    allowed, reason = snap.openai_live_allowed()
    assert allowed is True
    assert reason == ""
    assert snap.rules_version == "3.2"


def test_golden_calibration_includes_watch_cases():
    import json

    rows = json.loads(Path("fixtures/golden_lead_calibration.json").read_text(encoding="utf-8"))
    ids = {row["id"] for row in rows}
    assert "watch_price_uz" in ids
    assert "watch_plus_defer" in ids


def test_app_css_has_dark_mode_tokens():
    css = Path("app/web/static/app.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    assert "--bg: #0b1220" in css


def test_update_state_notes_builder():
    done, total = _plan_progress()
    assert done >= 100
    assert total == 120
    md = build_state_md(wave_line="wave17: test")
    assert "plan:" in md
    assert "wave17: test" in md


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM handlers skipped on Windows")
async def test_shutdown_handler_sets_event_on_signal():
    shutdown_event = asyncio.Event()
    handlers: dict[int, object] = {}
    loop = asyncio.get_running_loop()

    def fake_add_signal_handler(sig, callback):
        handlers[sig] = callback

    loop.add_signal_handler = fake_add_signal_handler  # type: ignore[method-assign]
    _install_shutdown_handlers(shutdown_event)
    assert signal.SIGTERM in handlers
    handlers[signal.SIGTERM]()  # type: ignore[operator]
    assert shutdown_event.is_set()


async def test_pipeline_limits_concurrent_analysis_under_load():
    concurrent = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    class DummyLeadService:
        session_factory = None

        async def analyze_lead(self, lead_id: int):
            nonlocal concurrent, max_concurrent
            async with lock:
                concurrent += 1
                max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.04)
            async with lock:
                concurrent -= 1
            return type(
                "R",
                (),
                {"lead_id": lead_id, "is_hot": False, "significant_change_id": None},
            )()

    class DummyNotifier:
        async def notify_analyzed_lead(self, lead_id: int) -> int:
            return 0

    pipeline = LeadAnalysisPipeline(
        DummyLeadService(),  # type: ignore[arg-type]
        DummyNotifier(),  # type: ignore[arg-type]
        max_concurrency=2,
        sync_mode=False,
    )
    await pipeline.start()
    for lead_id in range(1, 9):
        await pipeline.enqueue(lead_id)
    await pipeline.flush()
    await pipeline.stop()
    assert max_concurrent <= 2
    assert max_concurrent >= 2
