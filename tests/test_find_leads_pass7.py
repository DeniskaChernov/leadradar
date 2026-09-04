"""Find-leads pass7: soft geo/lang hints (UI-only, no scan payload)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_leads_pass7_geo_lang_soft_hints():
    wizard = (
        PROJECT_ROOT / "app/web/templates/partials/find_leads_wizard.html"
    ).read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")

    assert "data-find-lang-soft" in wizard
    assert "data-find-geo-soft" in wizard
    assert "data-sum-soft" in wizard
    assert "не жёсткий фильтр" in wizard or "не жёсткий фильтр" in js
    assert "не выдумывает" in wizard or "не выдумываем" in wizard
    assert "data-find-lang-soft" in js
    assert "data-find-geo-soft" in js
    assert "find-soft-tip" in css
    assert "13.44.0-copy-sweep" in base
