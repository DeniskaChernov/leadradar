"""Каждая вкладка структурирована под свою задачу."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = ROOT / "app/web/templates"
BASE = (T / "base.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/web/static/app.css").read_text(encoding="utf-8")


def _read(name: str) -> str:
    return (T / name).read_text(encoding="utf-8")


def test_nav_no_monitoring_duplicate() -> None:
    assert "Мониторинг" not in BASE
    assert ">Настройки</b>" in BASE
    assert ">Задачи</b>" in BASE
    assert ">Сделки</b>" in BASE
    # один пункт /system в secondary
    assert BASE.count('href="/system') + BASE.count("href=\"/system{{") >= 1


def test_hot_is_write_workspace_only() -> None:
    hot = _read("hot.html")
    assert 'data-page-task="hot"' in hot
    assert "hot-workspace" in hot
    assert "Горячие в поиске" not in hot
    assert "Клиенты HOT" not in hot
    assert "hot-openai-meter" not in hot
    assert "page-task-meta" in hot or "GPT сегодня" in hot or "GPT выключен" in hot
    assert "{% block heading %}HOT{% endblock %}" in hot
    assert ">HOT</b>" in BASE
    assert "Новые лиды" not in BASE


def test_dashboard_is_now_actions() -> None:
    dash = _read("dashboard.html")
    assert 'data-page-task="home"' in dash
    assert "operations-strip" not in dash
    assert "Требует внимания" in dash
    assert dash.count('class="quick-action"') == 4
    assert 'href="/system"' not in dash
    assert 'href="/economics"' not in dash
    assert 'href="/agent"' not in dash


def test_leads_funnel_not_settings_hub() -> None:
    leads = _read("leads.html")
    assert 'data-page-task="leads"' in leads
    assert "lead_reanalyze_actions" not in leads
    assert "data-agent-open" not in leads


def test_contacts_directory_only() -> None:
    contacts = _read("contacts.html")
    assert 'data-page-task="contacts"' in contacts
    assert "hero-actions" not in contacts


def test_system_is_settings_not_sales_desk() -> None:
    system = _read("system.html")
    assert 'data-page-task="system"' in system
    assert "Настройки" in system
    assert "не рабочий стол продаж" in system
    assert "system-toc-group" in system
    assert 'id="ai-quality-secondary"' in system
    assert "page-task-secondary" in system
    assert 'id="agent-workspace"' in system
    assert "Feedback, версии и offline-проверки" in system
    assert "Готовность Telegram" in system
    assert "AI lease и бюджет" in system
    assert 'id="ai-safety"' in system


def test_competitors_sources_first() -> None:
    competitors = _read("competitors.html")
    assert 'data-page-task="competitors"' in competitors
    assert "page-task-secondary" in competitors
    assert "Добавить источник" in competitors
    assert "ПОРТФЕЛЬ" in competitors
    assert "МОНИТОРИНГ" not in competitors


def test_analytics_audience_agent_page_task() -> None:
    analytics = _read("analytics.html")
    assert 'data-page-task="analytics"' in analytics
    assert "learning-card" in analytics
    assert "page-task-secondary" in analytics
    assert 'href="/system"' not in analytics
    aq = _read("audience_quality.html")
    assert 'data-page-task="audience-quality"' in aq
    assert "hero-actions" not in aq
    ad = _read("audience_detail.html")
    assert 'data-page-task="audience-detail"' in ad
    assert "meta-readiness page-task-secondary" in ad
    assert "</details>" in ad
    assert 'data-page-task="competitor-detail"' in _read("competitor_detail.html")
    assert 'data-page-task="agent"' in _read("agent.html")


def test_work_desk_hides_idle_status_pill() -> None:
    assert "show_ops_pill" in BASE
    assert "work_desk" in BASE
    assert "startswith('/hot')" in BASE
    assert "startswith('/leads')" in BASE
    assert "startswith('/contacts')" in BASE
    # idle «Готов» только если show_ops_pill
    assert "Готов · проверка не запущена" in BASE
    pill_block = BASE.split("{% if show_ops_pill %}")[1].split("{% endif %}")[0]
    assert "Готов · проверка не запущена" in pill_block


def test_lead_detail_action_first() -> None:
    lead = _read("lead_detail.html")
    assert 'data-page-task="lead-detail"' in lead
    assert 'id="funnel"' in lead
    # AI во вторичном details, не выше воронки
    funnel_pos = lead.find('id="funnel"')
    ai_pos = lead.find('id="lead-ai"')
    assert funnel_pos != -1 and ai_pos != -1
    assert funnel_pos < ai_pos
    assert "details class=\"panel ai-intelligence page-task-secondary\"" in lead or "ai-intelligence page-task-secondary" in lead
    assert "system#agent-workspace" not in _read("openings.html")


def test_desktop_nav_more_css() -> None:
    assert ".sidebar .nav-more" in CSS
    assert ".sidebar .nav-secondary.is-open" in CSS
    assert "nav-secondary:has(.nav.active)" in CSS


def test_hot_queue_scroll_and_auto_select() -> None:
    assert "hot-queue-list" in CSS
    assert "overflow-y:auto" in CSS
    assert "align-items:stretch" in CSS
    app_py = (ROOT / "app/web/app.py").read_text(encoding="utf-8")
    assert "сразу открываем первого в очереди" in app_py
    assert 'queue[0]["lead_id"]' in app_py


def test_work_shell_hides_scan_on_crm_pages() -> None:
    assert "show_top_scan" in BASE
    assert "startswith('/radar')" in BASE
    assert "startswith('/system')" in BASE
    assert "startswith('/competitors')" in BASE
    show_line = next(line for line in BASE.splitlines() if "show_top_scan" in line)
    assert "/hot" not in show_line
    assert "/leads" not in show_line


def test_contact_detail_work_first() -> None:
    contact = _read("contact_detail.html")
    assert 'data-page-task="contact"' in contact
    assert "Лиды в воронке" in contact
    assert "page-task-secondary" in contact
    assert "АУДИТОРИЯ И ИНТЕРЕСЫ" in contact
    leads_pos = contact.find("Лиды в воронке")
    audience_pos = contact.find("Аудитория и интересы")
    assert leads_pos != -1 and audience_pos != -1
    assert leads_pos < audience_pos


def test_page_task_css_and_cache() -> None:
    assert "Page-task structure" in CSS
    assert "13.52.0-hot-nav" in BASE
    assert "13.52.0-hot-nav" in (ROOT / "app/web/static/sw.js").read_text(encoding="utf-8")
