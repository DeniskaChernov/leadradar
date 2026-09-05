"""Десктоп shell: сайдбар и правая колонка помещаются в высоту viewport."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
BASE = (ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
SW = (ROOT / "app/web/static/sw.js").read_text(encoding="utf-8")


def test_sidebar_viewport_fit_css_present() -> None:
    assert "Sidebar viewport fit" in CSS
    assert "overflow-y: auto" in CSS
    assert "@media (min-width: 721px) and (max-height: 860px)" in CSS
    assert "@media (min-width: 721px) and (max-height: 720px)" in CSS
    assert ".sidebar .nav {" in CSS
    assert ".sidebar .side-info" in CSS


def test_right_column_viewport_fit_css_present() -> None:
    assert "Right column viewport fit" in CSS
    assert "max-height: calc(100vh - 128px)" in CSS
    assert ".lead-side," in CSS
    assert ".contact-side" in CSS


def test_side_fit_cache_bumped() -> None:
    assert "13.52.0-hot-nav" in BASE
    assert "13.52.0-hot-nav" in SW
