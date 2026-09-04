"""Work pages polish: contacts/deals/tasks + auth/agent find-leads language."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_work_pages_human_find_leads_language():
    contacts = (PROJECT_ROOT / "app/web/templates/contacts.html").read_text(
        encoding="utf-8"
    )
    deals = (PROJECT_ROOT / "app/web/templates/deals.html").read_text(encoding="utf-8")
    tasks = (PROJECT_ROOT / "app/web/templates/tasks.html").read_text(encoding="utf-8")
    auth = (PROJECT_ROOT / "app/web/templates/auth.html").read_text(encoding="utf-8")
    agent = (PROJECT_ROOT / "app/web/templates/agent.html").read_text(encoding="utf-8")
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    sw = (PROJECT_ROOT / "app/web/static/sw.js").read_text(encoding="utf-8")

    assert "БАЗА ЛЮДЕЙ" in contacts
    assert "Найти лидов" in contacts
    assert "Перейти в радар" not in contacts
    assert "РЕЗУЛЬТАТ ПРОДАЖ" in deals
    assert "Найти лидов" in deals
    assert "К лидам" not in deals
    assert "Кому писать" in tasks
    assert "Написать сейчас" in tasks
    assert "нужна мебель" in auth
    assert "База лидов доступна" not in auth
    assert "Статус поиска" in agent
    assert ">Радар<" not in agent
    assert "Горячие клиенты" in base
    assert "HOT лиды" not in base
    assert "13.44.0-copy-sweep" in base
    assert "13.44.0-copy-sweep" in auth
    assert "13.44.0-copy-sweep" in sw
