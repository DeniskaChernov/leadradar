"""Shell human copy: Radar → Найти лидов; dashboard/lead detail."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_shell_human_find_leads_language():
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    dashboard = (PROJECT_ROOT / "app/web/templates/dashboard.html").read_text(
        encoding="utf-8"
    )
    detail = (PROJECT_ROOT / "app/web/templates/lead_detail.html").read_text(
        encoding="utf-8"
    )
    help_radar = (
        PROJECT_ROOT / "app/web/templates/partials/radar_plain_help.html"
    ).read_text(encoding="utf-8")
    sw = (PROJECT_ROOT / "app/web/static/sw.js").read_text(encoding="utf-8")

    assert "Найти лидов" in base
    assert "Запуск Radar" not in base
    assert "Открыть Радар" not in base
    assert "Запустить Radar" not in base
    assert "Запустить Radar" not in js
    assert "Найти лидов?" in js
    assert "Найти лидов" in dashboard
    assert "Запустите Radar" not in dashboard
    assert "Клиент #" in detail
    assert "Клиенты" in detail
    assert "Как читать результаты поиска" in help_radar
    assert "13.54.0-f5-hot-ops" in base
    assert "13.54.0-f5-hot-ops" in sw
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert "РЕЗУЛЬТАТЫ ПОИСКА" in radar
    assert "РАДАР СИГНАЛОВ" not in radar
