from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_web_shell_exposes_light_theme_and_accessible_navigation():
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")

    assert '<meta name="color-scheme" content="light dark">' in base
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
    signal_buttons = (
        PROJECT_ROOT / "app/web/templates/partials/signal_review_buttons.html"
    ).read_text(encoding="utf-8")

    assert "AI-РАЗБОР СИГНАЛА" in lead_detail
    assert "recommended_action" in lead_detail
    assert "next_best_action" in lead_detail
    assert "ai_source_label(lead.ai_source)" in lead_detail
    assert "РЕКОМЕНДАЦИЯ ИЗ КАТАЛОГА" in lead_detail
    assert "catalog_recommendation.match_reasons" in lead_detail
    assert "risk_flags" in lead_detail
    assert 'data-lucide="circle-help"' in lead_detail
    assert 'data-label="Оценка"' in radar
    assert "РАДАР СИГНАЛОВ" in radar
    assert "partials/signal_review_actions.html" in radar
    assert "Оценить накопившееся" in signal_buttons
    assert "/api/signals/review-all" in signal_buttons


def test_v41_signal_first_states_and_notification_modes_are_manager_readable():
    system = (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    competitors = (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(
        encoding="utf-8"
    )
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")

    assert "УВЕДОМЛЕНИЯ МЕНЕДЖЕРУ" in system
    assert "Готовность Telegram-уведомлений" in system
    assert "ПРОВЕРКА · БЕЗ ОТПРАВКИ" in system
    assert "OFFLINE CHALLENGE" in system or "ОФЛАЙН-ПРОВЕРКА" in system
    assert "Качество локального интеллекта" in system
    assert "production accuracy" in system
    assert "INDEPENDENT QUALITY GATES" in system or "НЕЗАВИСИМЫЕ GATES" in system
    assert "Каждый новый комментарий" in (
        PROJECT_ROOT / "app/web/labels.py"
    ).read_text(encoding="utf-8")
    assert "Только покупательский интерес" in (
        PROJECT_ROOT / "app/web/labels.py"
    ).read_text(encoding="utf-8")
    assert "Только горячие лиды" in (
        PROJECT_ROOT / "app/web/labels.py"
    ).read_text(encoding="utf-8")
    assert "notification_policy_label" in competitors
    assert "Лид уже виден менеджеру" in radar


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
    assert "ГРУППЫ СПРОСА" in audiences
    assert "автоматически" in audiences
    assert "Качество аудиторий" in audiences
    assert "Instagram username не превращается" in audiences
    assert "CAMPAIGN BRIEF" in detail or "БРИФ КАМПАНИИ" in detail
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

    assert "РАЗВЕДКА КОНКУРЕНТОВ" in overview
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
    discovery = (PROJECT_ROOT / "app/web/templates/discovery.html").read_text(encoding="utf-8")

    assert "--primary: #3155ff" in css
    assert ".sidebar .nav { flex: 0 0 56px; }" in css
    assert "dashboard-metrics" in dashboard
    assert 'class="metric warn" href="/tasks"' in dashboard
    assert 'aria-label="Поиск по радару"' in radar
    assert 'aria-label="Фильтр по конкуренту"' in radar
    assert 'href="/discovery"' in competitors
    assert "candidate-grid" in discovery
    assert 'name="tier" aria-label=' in competitors


def test_interface_hardening_keeps_dense_views_accessible():
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    economics = (PROJECT_ROOT / "app/web/templates/economics.html").read_text(
        encoding="utf-8"
    )
    analytics = (PROJECT_ROOT / "app/web/templates/analytics.html").read_text(
        encoding="utf-8"
    )
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")

    assert 'role="dialog" aria-modal="true"' in base
    assert 'aria-describedby="confirm-text"' in base
    assert 'aria-current="page"' in economics
    assert "stage_count * 100 / funnel_peak" in analytics
    assert "analytics-hero" in analytics
    assert "analytics-period" in analytics
    assert 'href="/dashboard"' not in analytics
    assert 'href="/"' in analytics
    assert "table-scroll-hint" in css
    assert "more-navigation-open" in javascript
    assert "enhanceClickableRows" in javascript
    assert "event.key === 'Escape'" in javascript
    assert ".page-help b { white-space: normal; }" in css


def test_mobile_rattan_cards_and_opening_review_use_shared_safe_actions():
    rattan = (PROJECT_ROOT / "app/web/templates/rattan.html").read_text(encoding="utf-8")
    openings = (PROJECT_ROOT / "app/web/templates/openings.html").read_text(
        encoding="utf-8"
    )
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")

    assert 'class="responsive-table rattan-table"' in rattan
    assert 'data-label="Сигнал"' in rattan
    assert "Портфель пуст" in rattan
    assert "источников с вертикалью Ротанг" in rattan
    assert "Коммерческие сигналы ротанга" in rattan
    assert ".rattan-table thead { display: none; }" in css
    assert 'data-api-action="/api/openings/' in openings
    assert 'data-payload=\'{"decision":"VERIFIED"}\'' in openings
    assert 'data-confirm="Подтвердить этот публичный сигнал' in openings
    assert 'class="responsive-table openings-table"' in openings
    assert 'data-label="Заведение"' in openings
    assert "reviewOpening(" not in openings
    assert "<script>" not in openings


def test_pilot_cockpit_quick_actions_and_scan_modal():
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    dashboard = (PROJECT_ROOT / "app/web/templates/dashboard.html").read_text(
        encoding="utf-8"
    )
    javascript = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")

    assert 'id="scan-quick"' in base
    assert "scan_budget_quick" in base
    assert "quick-actions" in dashboard
    assert 'href="/agent"' in dashboard
    assert "Кабина пилота" in dashboard
    assert "openScanQuickModal" in javascript
    assert "runScan" in javascript
    assert ".quick-actions" in css


def test_economics_page_has_hero_and_safe_credit_accuracy():
    economics = (PROJECT_ROOT / "app/web/templates/economics.html").read_text(
        encoding="utf-8"
    )
    assert "hero-status economics-hero" in economics
    assert "safe_attr(page.credits, 'confirmed_coverage_percent')" in economics
    assert "segmented-control" in economics
    assert "Входные токены" in economics
    assert "Валовая прибыль" in economics
    assert 'data-label="Горячие"' in economics


def test_premium_glass_shell_motion_and_mobile_navigation_are_accessible():
    base = (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    auth = (PROJECT_ROOT / "app/web/templates/auth.html").read_text(encoding="utf-8")
    contacts = (PROJECT_ROOT / "app/web/templates/contacts.html").read_text(
        encoding="utf-8"
    )
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")

    assert "13.29.3-bugfix" in base
    assert "13.29.3-bugfix" in auth
    assert "data-motion-root" in auth
    assert "ВХОД · TELEGRAM" in auth
    assert "fonts.googleapis.com" in base
    assert 'href="/catalog"' in base
    assert 'href="/discovery"' in base
    assert 'id="agent-quick"' in base
    assert "data-agent-open" in base
    assert 'data-more-toggle aria-expanded="false"' in base
    assert 'aria-controls="more-navigation"' in base
    assert 'aria-label="Вертикаль бизнеса"' in base
    assert 'aria-current="page"' in base
    assert 'data-toast-message' in base
    assert 'class="responsive-table"' in contacts
    assert 'data-label="Клиент"' in contacts

    assert "--motion-base: 240ms" in css
    assert ".nav-secondary.is-open" in css
    assert ".motion-ready [data-reveal].is-visible" in css
    assert "@keyframes toast-progress" in css
    assert ".modal-backdrop.is-open .modal" in css
    assert "body.more-navigation-open .mobile-nav-backdrop" in css

    assert "new IntersectionObserver" in javascript
    assert "event.key === 'Tab'" in javascript
    assert "sessionStorage.setItem('lr:scroll-y'" in javascript
    assert "setLoading" in javascript
    assert "prefers-reduced-motion: reduce" in javascript
    assert "let radarWasBusy" in javascript
    assert "if (radarWasBusy && !stillBusy)" in javascript


def test_mobile_responsive_tables_and_economics_wrap_at_720px():
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    economics = (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    audience_quality = (PROJECT_ROOT / "app/web/templates/audience_quality.html").read_text(
        encoding="utf-8"
    )

    assert "@media (max-width: 720px)" in css
    assert ".responsive-table thead { display: none; }" in css
    assert ".responsive-table td::before" in css
    assert "content: attr(data-label)" in css
    assert ".economics-table-wrap" in css
    assert "economics-table-wrap" in economics
    assert 'class="responsive-table audience-health-table"' in audience_quality
    assert 'data-label="Статус"' in audience_quality
    assert 'data-label="Увер."' in audience_quality
    assert "body.more-navigation-open .mobile-nav-backdrop" in css
    assert ".nav-primary { grid-template-columns: repeat(4,minmax(0,1fr))" in css
    assert "padding-bottom: calc(78px + env(safe-area-inset-bottom))" in css
    assert ".filters { top: 78px; }" in css


def test_contact_qualification_and_intelligence_sections_have_explicit_layouts():
    contact = (PROJECT_ROOT / "app/web/templates/contact_detail.html").read_text(
        encoding="utf-8"
    )
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")

    assert 'class="knowledge-grid"' in contact
    assert 'class="edit-knowledge"' in contact
    assert 'class="interest-columns"' in contact
    assert ".knowledge-grid {" in css
    assert ".knowledge-grid > div" in css
    assert ".interest-columns {" in css
    assert ".edit-knowledge > summary" in css
    assert ".audience-profile > .intelligence-summary" in css


def test_radar_budget_ui_uses_credit_presets_truthful_max_and_result_facts():
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    javascript = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")

    assert "Сколько разрешить на эту проверку?" in radar
    assert "Максимальный расход" in radar
    assert "Потрачено" in radar
    assert "ПОСЛЕДНИЙ ЗАПУСК" in radar
    for preset in ("Эконом", "Обычно", "Расширенно", "Глубоко"):
        assert preset in radar
    assert "max_credits" in javascript
    assert "getAttribute('method')" in javascript
    assert 'method="post" action="/api/ops/openai-live"' in radar
    assert "Использовано за месяц" in javascript
    assert ".radar-budget-card" in css
    assert ".scan-result-grid" in css


def test_app_js_has_single_escape_html_helper():
    javascript = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    assert javascript.count("const escapeHtml =") == 1
    assert "data-stage" in javascript
    assert "data-lead-action" in javascript


def test_phase8_system_agent_export_and_telegram_workspaces():
    system = (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    radar = (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    economics = (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    lead_detail = (PROJECT_ROOT / "app/web/templates/lead_detail.html").read_text(encoding="utf-8")
    contact_detail = (PROJECT_ROOT / "app/web/templates/contact_detail.html").read_text(
        encoding="utf-8"
    )
    audience_detail = (PROJECT_ROOT / "app/web/templates/audience_detail.html").read_text(
        encoding="utf-8"
    )
    javascript = (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    css = (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")

    assert "АССИСТЕНТ · ТОЛЬКО БАЗА" in system
    assert "system-hero" in system
    assert "system-toc" in system
    assert "review-all" in system or "signal_review_actions" in system
    assert "responsive-table system-table" in system
    assert "system-run-history" in system
    assert "partials/signal_review_actions.html" in radar
    assert "rattan-metrics" in (PROJECT_ROOT / "app/web/templates/rattan.html").read_text(encoding="utf-8")
    assert ".rattan-metrics" in css
    assert 'name="contact_id"' in contact_detail
    assert "data-agent-query" in system
    assert "Export recipes preview" in system or "Предпросмотр export recipes" in system
    assert "export-recipe-grid" in system
    assert "Локальный режим без Telegram auth" in system
    assert "responsive-table" in economics
    assert "economics-table-wrap" in economics
    assert 'data-label="Источник"' in economics
    assert 'data-label="Провайдер"' in economics
    assert 'data-label="Вертикаль"' in economics
    assert "lead-agent-panel" in lead_detail
    assert "/api/leads/{{ lead.id }}/analyze" in lead_detail
    assert "ai-intelligence" in lead_detail
    assert "data-agent-query" in lead_detail
    assert 'name="lead_id" value="{{ lead.id }}"' in lead_detail
    assert "lead-agent-result" in lead_detail
    assert "agent-preset" in lead_detail
    assert "contact-agent-result" in contact_detail
    assert "hero-status radar-hero" in radar
    assert "radar-metrics" in radar
    assert ".radar-metrics" in css
    assert "leads-hero" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "partials/lead_funnel_quick_action.html" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    funnel_partial = (PROJECT_ROOT / "app/web/templates/partials/lead_funnel_quick_action.html").read_text(encoding="utf-8")
    assert "data-stage" in funnel_partial
    assert "data-lead-action" in funnel_partial
    assert "leads-save-trust" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "partials/lead_reanalyze_actions.html" in (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    assert "reanalyze-batch" in (PROJECT_ROOT / "app/web/templates/partials/lead_reanalyze_actions.html").read_text(encoding="utf-8")
    assert "include_not_lead_high_score" in (PROJECT_ROOT / "app/web/templates/partials/lead_reanalyze_actions.html").read_text(encoding="utf-8")
    assert "feedback-learning" in (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    assert "feedback-export" in (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    assert "lead_event_history_tip.html" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "kanban-event-tip-trigger" in (PROJECT_ROOT / "app/web/templates/partials/lead_event_history_tip.html").read_text(encoding="utf-8")
    assert "kanban-mobile-nav" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "data-toast-undo" in (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "enhanceKanbanMobile" in (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    assert "competitors-hero" in (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(encoding="utf-8")
    assert "lead_quality_badge.html" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "quality=garbage" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "radar_plain_help" in (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert "WON" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "lead_bulk_actions.html" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "dashboard_plain_help" in (PROJECT_ROOT / "app/web/templates/dashboard.html").read_text(encoding="utf-8")
    assert "data-lead-followup" in (PROJECT_ROOT / "app/web/templates/partials/lead_funnel_quick_action.html").read_text(encoding="utf-8")
    assert "Вернуть в работу" in (PROJECT_ROOT / "app/web/templates/partials/lead_funnel_quick_action.html").read_text(encoding="utf-8")
    assert "Просрочен контакт" in (PROJECT_ROOT / "app/web/templates/partials/lead_quality_badge.html").read_text(encoding="utf-8")
    assert "Спорные" in (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert "LEAD_SEARCH_ENABLED=false" in (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert "провайдер подтвердил" in (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    assert "Очередь оценки" in (PROJECT_ROOT / "app/web/templates/agent.html").read_text(encoding="utf-8")
    assert "data-lead-followup" in javascript
    assert "/api/leads/" in javascript and "follow-up" in javascript
    assert ".leads-bulk-bar" in css
    assert "showScanSummary" in javascript
    assert "scan-summary" in (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert ".scan-summary-grid" in css
    assert "main-sticky-head" in (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "data-scan-progress-banner" in (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert ".main-sticky-head" in css
    assert "data-scan-progress-block" in (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert "applyScanProgress" in javascript
    assert "/api/scan/progress" in javascript
    assert ".scan-progress-banner" in css
    assert ".scan-progress-track" in css
    assert "competitor_tier_label" in (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert "radar-table-empty" in (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert 'href="#radar-live-arm"' in (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert "data-competitor-bulk" in (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(encoding="utf-8")
    assert "competitors-plain-help" in (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(encoding="utf-8")
    assert "notification_policy_label" in (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(encoding="utf-8")
    assert "data-confirm-danger" in (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(encoding="utf-8")
    assert "confirmAction" in javascript and "options.danger" in javascript
    assert "/api/competitors/bulk-active" in javascript
    assert ".competitors-bulk-bar" in css
    assert "data-budget-plan" in (PROJECT_ROOT / "app/web/templates/radar.html").read_text(encoding="utf-8")
    assert "data-scan-quick-plan" in (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "formatScanPreviewMeta" in javascript
    assert "burn-sparkline" in (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    assert "economics-low-alert" in (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    assert 'href="/radar#radar-budget-title"' in (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    assert "credits/HOT" in (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    assert "tier-suggest" in (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(encoding="utf-8")
    assert "Ошибки скана" in (PROJECT_ROOT / "app/web/templates/competitors.html").read_text(encoding="utf-8")
    assert "data-gpt-queue" in (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "applyGptQueueChip" in javascript
    assert "readAgentContext" in javascript
    assert "/api/leads/export.csv" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "manager-feedback-quality" in (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    assert "В радар активно" in (PROJECT_ROOT / "app/web/templates/discovery.html").read_text(encoding="utf-8")
    assert "data-agent-context" in (PROJECT_ROOT / "app/web/templates/lead_detail.html").read_text(encoding="utf-8")
    assert "13.29.3-bugfix" in (PROJECT_ROOT / "app/web/templates/base.html").read_text(encoding="utf-8")
    assert "kanban-drag-handle" in (PROJECT_ROOT / "app/web/templates/leads.html").read_text(encoding="utf-8")
    assert "data-economics-budget-sim" in (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    assert "ai-version-info" in (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    assert "enhanceEconomicsBudgetSim" in (PROJECT_ROOT / "app/web/static/app.js").read_text(encoding="utf-8")
    assert "is-loading" in (PROJECT_ROOT / "app/web/static/app.css").read_text(encoding="utf-8")
    assert "/api/economics/export.csv" in (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    assert "openai_usd_per_lead" in (PROJECT_ROOT / "app/web/templates/economics.html").read_text(encoding="utf-8")
    assert "proxy cache-hit" in (PROJECT_ROOT / "app/web/templates/system.html").read_text(encoding="utf-8")
    assert "lead-assign" in (PROJECT_ROOT / "app/web/templates/lead_detail.html").read_text(encoding="utf-8")
    assert "GPT выключен" in (PROJECT_ROOT / "app/web/templates/lead_detail.html").read_text(encoding="utf-8")
    assert "focusKeyForElement" in javascript
    assert "openai_cost" in (PROJECT_ROOT / "app/web/templates/lead_detail.html").read_text(encoding="utf-8")
    assert "contacts-hero" in (PROJECT_ROOT / "app/web/templates/contacts.html").read_text(encoding="utf-8")
    assert 'href="/agent"' in (PROJECT_ROOT / "app/web/templates/contacts.html").read_text(encoding="utf-8")
    assert "ОЧЕРЕДЬ КОНТАКТОВ" in (PROJECT_ROOT / "app/web/templates/tasks.html").read_text(encoding="utf-8")
    assert "ВОРОНКА СДЕЛОК" in (PROJECT_ROOT / "app/web/templates/deals.html").read_text(encoding="utf-8")
    assert "tasks-hero" in (PROJECT_ROOT / "app/web/templates/tasks.html").read_text(encoding="utf-8")
    assert "deals-hero" in (PROJECT_ROOT / "app/web/templates/deals.html").read_text(encoding="utf-8")
    assert "V3.5 · unified airy rhythm" in css
    assert "--space-8: 40px" in css
    assert "audience-quality-hero" in (PROJECT_ROOT / "app/web/templates/audience_quality.html").read_text(encoding="utf-8")
    assert "lead-agent-panel" in contact_detail
    assert "@{{ contact.username }}" in contact_detail
    assert "data-agent-query" in contact_detail
    assert "export_recipe" in audience_detail
    assert "disableVerticalSwipes" in javascript
    assert "renderAgentAnswer" in javascript
    assert "formatExportPreview" in javascript
    assert ".agent-workspace" in css
    assert ".lead-agent-panel.compact" in css
    assert ".export-recipe-grid" in css
