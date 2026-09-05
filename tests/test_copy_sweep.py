"""Copy-sweep: residual find-leads language leftovers."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_copy_sweep_rattan_openings_offline():
    rattan = (PROJECT_ROOT / "app/web/templates/rattan.html").read_text(encoding="utf-8")
    openings = (PROJECT_ROOT / "app/web/templates/openings.html").read_text(
        encoding="utf-8"
    )
    offline = (PROJECT_ROOT / "app/web/static/offline.html").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    competitors = (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(
        encoding="utf-8"
    )

    assert "ПОРТФЕЛЬ РОТАНГА" in rattan
    assert "Лиды ротанга" not in rattan
    assert "Новые заведения" in openings
    assert "Радар открытий" not in openings
    assert "B2B ОТКРЫТИЯ" in openings
    assert "13.54.0-f5-hot-ops" in offline
    assert "данные CRM и API" not in offline
    assert "нужен Live-поиск" in competitors
    assert "13.54.0-f5-hot-ops" in base
    system = (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    wizard = (
        PROJECT_ROOT / "app/web/templates/partials/find_leads_wizard.html"
    ).read_text(encoding="utf-8")
    assert "Live-поиск" in system
    assert "Включить Live Radar" not in system
    assert "Включить Live-поиск" in radar
    assert "Включить Live Radar" not in radar
    assert "Включить Live-поиск" in wizard
