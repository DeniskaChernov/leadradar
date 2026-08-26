from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_web_shell_exposes_light_theme_and_accessible_navigation():
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")

    assert '<meta name="color-scheme" content="light">' in base
    assert 'class="skip-link"' in base
    assert 'aria-label="Основная навигация"' in base
    assert 'id="main-content"' in base
    assert "lucide@1.34.0" in base


def test_liquid_glass_theme_has_fallback_and_reduced_motion_support():
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")

    assert "V3.4 · light liquid-glass design system" in css
    assert "backdrop-filter: blur(20px)" in css
    assert "@supports not" in css
    assert "prefers-reduced-motion: reduce" in css
