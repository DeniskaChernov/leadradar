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

    assert "Клиенты · ротанг" in rattan
    assert "Лиды ротанга" not in rattan
    assert "Новые заведения" in openings
    assert "Радар открытий" not in openings
    assert "Найти лидов" in openings
    assert "13.44.0-copy-sweep" in offline
    assert "данные CRM и API" not in offline
    assert "нужен Live-поиск" in competitors
    assert "13.44.0-copy-sweep" in base
