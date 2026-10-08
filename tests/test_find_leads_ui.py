"""UI composition: one supported manual scan flow on /radar."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_leads_wizard_partial_and_radar_wire():
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    wizard = (PROJECT_ROOT / "app/web/templates/partials/find_leads_wizard.html").read_text(
        encoding="utf-8"
    )
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    sw = (PROJECT_ROOT / "app/web/static/sw.js").read_text(encoding="utf-8")

    assert 'partials/find_leads_wizard.html' in radar or "find_leads_wizard" in radar
    assert "Найдите новых клиентов" in wizard
    assert "data-find-leads" in wizard
    assert "scan-launch" in wizard
    assert 'name="scan_budget"' in wizard
    assert "active_competitors" in wizard
    assert 'data-source="instagram"' in wizard
    assert "Ручной режим" in wizard
    assert "Открыть HOT" in wizard
    assert "а не обещанное число лидов" in wizard
    assert "Найти лидов" in wizard
    assert "monitor_schedule_enabled" in wizard
    assert "disabled" in wizard
    assert "Найти лидов" in base
    assert "data-nav-usage" in base
    assert "Текущий месяц" in base
    assert "enhanceFindLeadsWizard" not in js
    assert "refreshNavUsage" in js
    assert "lr:find-leads" in js
    assert ".find-leads" in css
    assert ".scan-launch" in css
    assert "13.56.0-cloudflare" in sw
    assert "13.56.0-cloudflare" in base
    # Safety/backend UI preserved on radar page
    assert "Сколько разрешить на эту проверку?" in wizard
    assert "Максимальный расход" in wizard
    assert 'method="post" action="/api/ops/openai-live"' in radar
    assert "Offline-режим" in radar or "scan_budget.is_live" in radar
    assert "data-scan" in wizard


def test_find_leads_no_fake_provider_launch_hooks():
    wizard = (PROJECT_ROOT / "app/web/templates/partials/find_leads_wizard.html").read_text(
        encoding="utf-8"
    )
    # Unsupported providers must not be offered as a search control.
    for source in ("telegram", "tiktok", "facebook", "olx", "glotr", "tenders", "web", "maps"):
        assert f'data-source="{source}"' not in wizard
        assert f'value="{source}"' not in wizard
    assert 'name="find_source"' not in wizard
