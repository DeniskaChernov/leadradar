"""CRM/HOT polish: human copy, empty states, CTA to find leads."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_crm_hot_human_copy_and_empty_states():
    hot = (PROJECT_ROOT / "app/web/templates/hot.html").read_text(encoding="utf-8")
    leads = (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    dashboard = (PROJECT_ROOT / "app/web/templates/dashboard.html").read_text(
        encoding="utf-8"
    )
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")

    assert "Кого писать" in hot
    assert "Пока некого писать" in hot
    assert "Найти лидов" in hot
    assert "Выберите клиента слева" in hot
    assert "ВОРОНКА ·" in leads
    assert "kanban-empty" in leads
    assert "leads-empty" in leads
    assert "Найти лидов" in leads
    assert "Написать сейчас" in leads
    assert ">Клиенты<" in base.replace(" ", "") or "<b>Клиенты</b>" in base
    assert "<b>Клиенты</b>" in dashboard
    assert ".kanban-empty" in css
    assert "13.54.0-f5-hot-ops" in base