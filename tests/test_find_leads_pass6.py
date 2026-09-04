"""Find-leads pass6: reset filter, kind sync, discovery/economics copy."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_leads_pass6_reset_sync_and_pages():
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    discovery = (PROJECT_ROOT / "app/web/templates/discovery.html").read_text(
        encoding="utf-8"
    )
    economics = (PROJECT_ROOT / "app/web/templates/economics.html").read_text(
        encoding="utf-8"
    )
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")

    assert "data-find-filter-reset" in radar
    assert "Сбросить фильтр поиска" in radar
    assert "clearFindLeadsPrefsFilter" in js
    assert "syncRadarKindSelect" in js
    assert "saved.step" in js
    assert "ЦЕНТР РАЗВЕДКИ" in discovery
    assert "Найти лидов" in discovery
    assert "Новые источники" in discovery or "Расширьте источники" in discovery
    assert "Найти лидов" in economics
    assert "РАСХОДЫ НА ПОИСК" in economics
    assert "Новые источники" in base
    assert "13.44.0-copy-sweep" in base
