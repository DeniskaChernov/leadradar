"""Find-leads pass4: audience/category prefs filter + dashboard copy."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_leads_pass4_prefs_filter_and_dashboard():
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    dashboard = (PROJECT_ROOT / "app/web/templates/dashboard.html").read_text(
        encoding="utf-8"
    )
    help_text = (
        PROJECT_ROOT / "app/web/templates/partials/dashboard_plain_help.html"
    ).read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")

    assert "data-find-filter-empty" in radar
    assert "По текущему фильтру поиска карточек нет" in radar
    assert "cardMatchesFindPrefs" in js
    assert "FIND_CATEGORY_PRODUCTS" in js
    assert "FIND_AUDIENCE_INTENTS" in js
    assert "categoryLabels" in js
    assert "Найти лидов" in dashboard
    assert "Что сделать сейчас" in dashboard
    assert "Найти лидов" in help_text
    assert "13.53.0-f1-portfolio" in base
