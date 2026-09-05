"""Find-leads pass5: table sync filter + autoscroll + competitors copy."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_leads_pass5_table_autoscroll_competitors():
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    competitors = (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(
        encoding="utf-8"
    )
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")

    assert "data-find-row" in radar
    assert "radar-signal-row" in radar
    assert "scrollToFindResultsIfNeeded" in js
    assert "lr:find-leads-pending-results" in js
    assert "visibleRows" in js or "data-find-row" in js
    assert "Источники поиска" in competitors
    assert "Добавить источник" in competitors
    assert ".radar-signal-row[hidden]" in css
    assert "13.52.0-hot-nav" in base
