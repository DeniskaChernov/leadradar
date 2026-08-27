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


def test_lead_detail_and_radar_expose_deep_responsive_analysis():
    lead_detail = (PROJECT_ROOT / "app/web/templates/lead_detail.html").read_text(
        encoding="utf-8"
    )
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")

    assert "ГЛУБОКИЙ AI-РАЗБОР" in lead_detail
    assert "recommended_action" in lead_detail
    assert "risk_flags" in lead_detail
    assert 'data-label="AI-оценка"' in radar


def test_v41_signal_first_states_and_notification_modes_are_manager_readable():
    system = (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    competitors = (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(
        encoding="utf-8"
    )
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")

    assert "УВЕДОМЛЕНИЯ МЕНЕДЖЕРУ" in system
    assert "Каждый новый комментарий" in competitors
    assert "Только покупательский интерес" in competitors
    assert "Только горячие лиды" in competitors
    assert "Сигнал уже сохранён и виден менеджеру" in radar


def test_audience_pages_explain_privacy_boundary_and_campaign_action():
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    audiences = (PROJECT_ROOT / "app/web/templates/audiences.html").read_text(
        encoding="utf-8"
    )
    detail = (PROJECT_ROOT / "app/web/templates/audience_detail.html").read_text(
        encoding="utf-8"
    )
    contact = (PROJECT_ROOT / "app/web/templates/contact_detail.html").read_text(
        encoding="utf-8"
    )

    assert 'href="/audiences"' in base
    assert "Чувствительные признаки не собираются" in audiences
    assert "Instagram username не превращается" in audiences
    assert "CAMPAIGN BRIEF" in detail
    assert "АУДИТОРИЯ И ИНТЕРЕСЫ" in contact


def test_significant_changes_are_actionable_and_explainable():
    dashboard = (PROJECT_ROOT / "app/web/templates/dashboard.html").read_text(
        encoding="utf-8"
    )
    contact = (PROJECT_ROOT / "app/web/templates/contact_detail.html").read_text(
        encoding="utf-8"
    )

    assert "Стали горячее" in dashboard
    assert "change.previous_priority" in dashboard
    assert "СУЩЕСТВЕННЫЕ ИЗМЕНЕНИЯ" in contact
    assert "Мелкие колебания" not in contact
    assert "мелкие колебания оценки" in contact


def test_competitor_intelligence_explains_data_boundary_and_actions():
    overview = (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(
        encoding="utf-8"
    )
    detail = (PROJECT_ROOT / "app/web/templates/competitor_detail.html").read_text(
        encoding="utf-8"
    )

    assert "COMPETITOR INTELLIGENCE V2" in overview
    assert "Пересечение спроса" in overview
    assert "Самые коммерчески эффективные публикации" in detail
    assert "Мы не утверждаем, что конкурент не ответил клиенту" in detail
    assert "Direct" in detail


def test_audit_fixes_navigation_alignment_and_accessible_filters():
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    dashboard = (PROJECT_ROOT / "app/web/templates/dashboard.html").read_text(
        encoding="utf-8"
    )
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    competitors = (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(
        encoding="utf-8"
    )

    assert "--primary: #3155ff" in css
    assert ".sidebar .nav { flex: 0 0 56px; }" in css
    assert "dashboard-metrics" in dashboard
    assert 'class="metric warn" href="/tasks"' in dashboard
    assert 'aria-label="Поиск по радару"' in radar
    assert 'aria-label="Фильтр по конкуренту"' in radar
    assert "market-candidates-disclosure" in competitors
    assert 'name="tier" aria-label=' in competitors
