"""UI regression: wizard «Найти лидов» на /radar."""

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
    assert "Найдите новых клиентов для вашего бизнеса" in wizard
    assert "data-find-leads" in wizard
    assert "data-find-panel=\"1\"" in wizard
    assert "data-find-panel=\"4\"" in wizard
    assert "Быстрый старт" in wizard
    assert "Рестораны и кафе" in wizard
    assert "Производители и опт" in wizard
    assert "Самый мощный источник" in wizard
    assert 'data-source-available="1"' in wizard
    assert 'data-source="instagram"' in wizard
    assert "Не подключено" in wizard or "Скоро" in wizard
    assert "Ваш поиск" in wizard
    assert "Пример результата" in wizard
    assert "UI-пример, не сохранён в базе" in wizard
    assert "Найти лидов →" in wizard
    assert "Следить постоянно" in wizard
    assert "disabled" in wizard
    assert "Найти лидов" in base
    assert "data-nav-usage" in base
    assert "Текущий месяц" in base
    assert "enhanceFindLeadsWizard" in js
    assert "refreshNavUsage" in js
    assert "lr:find-leads" in js
    assert ".find-leads" in css
    assert ".find-layout" in css
    assert ".find-source" in css
    assert "13.53.0-f1-portfolio" in sw
    assert "13.53.0-f1-portfolio" in base
    # Safety/backend UI preserved on radar page
    assert "Сколько разрешить на эту проверку?" in radar
    assert "Максимальный расход" in radar
    assert 'method="post" action="/api/ops/openai-live"' in radar
    assert "Offline-режим" in radar or "scan_budget.is_live" in radar
    assert "data-scan" in wizard


def test_find_leads_no_fake_provider_launch_hooks():
    wizard = (PROJECT_ROOT / "app/web/templates/partials/find_leads_wizard.html").read_text(
        encoding="utf-8"
    )
    # Недоступные источники не имеют enabled checkbox для запуска
    for source in ("telegram", "tiktok", "facebook", "olx", "glotr", "tenders", "web", "maps"):
        assert f'data-source="{source}"' in wizard
        assert f'value="{source}" disabled' in wizard
