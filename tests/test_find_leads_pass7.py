"""Unsupported ingestion preferences must not appear as search controls."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_find_leads_pass7_geo_lang_soft_hints():
    wizard = (
        PROJECT_ROOT / "app/web/templates/partials/find_leads_wizard.html"
    ).read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")

    assert 'name="find_lang"' not in wizard
    assert 'name="find_geo"' not in wizard
    assert "data-sum-soft" not in wizard
    assert "data-find-lang-soft" not in js
    assert "data-find-geo-soft" not in js
    assert ".scan-launch" in css
    assert "13.56.0-cloudflare" in base
