from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings
from app.db.models import Lead, LeadStatus, NotificationPolicy
from app.services.agent_rate_limit_service import agent_rate_limiter
from app.services.ai_service import (
    BudgetedCachedOpenAIAnalyzer,
    HybridLeadAnalyzer,
    OpenAILeadAnalyzer,
    RuleBasedLeadAnalyzer,
)
from app.services.audience_facet_service import AudienceFacetQuery
from app.services.audience_service import AudienceEngine
from app.services.competitor_import_service import CompetitorImportService
from app.services.crm_service import CRMService
from app.services.deployment_readiness_service import inspect_offline_readiness
from app.services.discovery_service import DiscoveryService
from app.services.export_recipe_service import ExportRecipeService
from app.services.feedback_learning_service import FeedbackLearningService
from app.services.fx_policy_service import FxPolicyService
from app.services.independent_quality_gates_service import IndependentQualityGatesService
from app.services.lead_analysis_pipeline import LeadAnalysisPipeline
from app.services.lead_intelligence_challenge import LeadIntelligenceChallenge
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowError, LeadWorkflowService
from app.services.market_intelligence_service import MarketIntelligenceService
from app.services.meta_audience_service import MetaAudiencePlanningService
from app.services.monitor_controller import MonitorController
from app.services.notification_readiness_service import NotificationReadinessService
from app.services.operational_control_service import OperationalControlService
from app.services.pricing_config_service import PricingConfigService
from app.services.product_catalog_service import (
    ALLOWED_PRODUCT_CATEGORIES,
    ProductCatalogService,
)
from app.services.provider_credit_budget_service import ProviderCreditBudgetService
from app.services.significant_change_service import SignificantChangeDetector
from app.services.telegram_notification_service import (
    resolve_uncertain_change_log,
    resolve_uncertain_lead_log,
)
from app.services.usage_service import ExternalUsageService
from app.web.auth import TelegramAuthError, TelegramWebAuth, WebRole, required_role
from app.web.datetime_display import format_display_dt, parse_display_dt
from app.web.labels import (
    AI_SOURCE_LABELS,
    AUDIENCE_HEALTH_LABELS,
    BUDGET_STATUS_LABELS,
    BUYER_ROLE_ICONS,
    BUYER_ROLE_LABELS,
    CHANGE_TYPE_LABELS,
    CHANNEL_LABELS,
    COMMERCIAL_STAGE_LABELS,
    COMPETITOR_CATEGORY_LABELS,
    COMPETITOR_TIER_LABELS,
    COVERAGE_LABELS,
    DEAL_STATUS_LABELS,
    EVENT_LABELS,
    EXPORT_ELIGIBILITY_LABELS,
    FUNNEL_STAGE_LABELS,
    INTENT_LABELS,
    LEAD_STATUS_LABELS,
    NOTIFICATION_POLICY_LABELS,
    PRODUCT_LABELS,
    PURCHASE_HORIZON_LABELS,
    QUALIFICATION_FIELD_LABELS,
    RUN_STATUS_LABELS,
    TRIGGER_LABELS,
    URGENCY_LABELS,
    label,
)
from app.web.lead_ui_helpers import (
    lead_is_off_catalog,
    lead_next_action_overdue,
    lead_quality_badge,
)
from app.web.queries import WebQueryService

logger = logging.getLogger(__name__)

_DEV_MUTATION_FORBIDDEN_DETAIL = (
    "Локальный режим без авторизации: задайте WEB_MANAGER_ID "
    "для изменяющих запросов к API."
)


def build_web_app(
    settings: Settings,
    queries: WebQueryService,
    workflow: LeadWorkflowService,
    controller: MonitorController,
    usage_service: ExternalUsageService | None = None,
    crm: CRMService | None = None,
    notification_worker_active: bool = False,
    ops_control: OperationalControlService | None = None,
    analysis_pipeline: LeadAnalysisPipeline | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Lead Radar",
        docs_url="/api/docs" if settings.web_auth_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.web_auth_enabled else None,
    )
    if settings.web_auth_enabled:
        configured_host = urlparse(settings.web_public_url).hostname
        allowed_hosts = {"127.0.0.1", "localhost", "testserver"}
        if configured_host:
            allowed_hosts.add(configured_host)
        if settings.web_host not in {"0.0.0.0", "::"}:
            allowed_hosts.add(settings.web_host)
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(allowed_hosts))
    root = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(root / "templates"))
    app.mount("/static", StaticFiles(directory=str(root / "static")), name="static")

    @app.get("/sw.js")
    async def service_worker_script():
        """SW на корневом path, чтобы scope=/ покрывал CRM shell."""
        return FileResponse(
            root / "static" / "sw.js",
            media_type="application/javascript; charset=utf-8",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-cache",
            },
        )

    auth = TelegramWebAuth(settings)
    usage_service = usage_service or ExternalUsageService(workflow.session_factory)
    provider_budget_service = ProviderCreditBudgetService(workflow.session_factory)
    crm = crm or CRMService(workflow.session_factory)
    ops_control = ops_control or OperationalControlService(workflow.session_factory)
    # analyze-local stays rules-only. retry-pending uses hybrid with live_gate.
    market_service = MarketIntelligenceService(workflow.session_factory)
    meta_audience_service = MetaAudiencePlanningService(workflow.session_factory)
    discovery_service = DiscoveryService(workflow.session_factory)
    competitor_import_service = CompetitorImportService(workflow.session_factory)
    product_catalog_service = ProductCatalogService(workflow.session_factory)
    local_audience_engine = AudienceEngine(workflow.session_factory, settings.hot_lead_threshold)
    change_detector = SignificantChangeDetector(
        workflow.session_factory, hot_threshold=settings.hot_lead_threshold
    )
    local_lead_service = LeadService(
        workflow.session_factory,
        HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), None, mode="hybrid"),
        settings.hot_lead_threshold,
        audience_engine=local_audience_engine,
        change_detector=change_detector,
        signal_max_age_days=settings.instagram_signal_max_age_days,
        rules_version=settings.lead_analysis_version,
    )
    openai_analyzer = None
    if settings.openai_api_key:
        openai_analyzer = BudgetedCachedOpenAIAnalyzer(
            OpenAILeadAnalyzer(settings.openai_api_key, settings.openai_model),
            workflow.session_factory,
            usage_service,
            enabled=settings.openai_live_enabled,
            daily_limit=settings.openai_daily_request_limit,
            analysis_version=settings.lead_analysis_version,
            lease_seconds=settings.ai_request_lease_seconds,
            max_attempts=settings.ai_request_max_attempts,
            live_gate=ops_control.openai_live_armed,
            live_refresh=ops_control.openai_live_armed_fresh,
            worker_id="web-hybrid",
        )
    hybrid_mode = settings.ai_mode if settings.ai_mode in {"rules", "hybrid", "openai"} else "hybrid"
    hybrid_lead_service = LeadService(
        workflow.session_factory,
        HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), openai_analyzer, mode=hybrid_mode),
        settings.hot_lead_threshold,
        audience_engine=local_audience_engine,
        change_detector=change_detector,
        signal_max_age_days=settings.instagram_signal_max_age_days,
        rules_version=settings.lead_analysis_version,
    )
    delivery_allowed_by_config = bool(settings.telegram_bot_token) and (
        settings.instagram_provider not in {"mock", "replay"}
    )
    notification_readiness_service = NotificationReadinessService(
        workflow.session_factory,
        workflow,
        manager_chat_ids=settings.telegram_manager_chat_ids,
        default_policy=NotificationPolicy(settings.notification_policy),
        hot_threshold=settings.hot_lead_threshold,
        token_configured=bool(settings.telegram_bot_token),
        delivery_allowed_by_config=delivery_allowed_by_config,
        worker_active=notification_worker_active,
    )

    def master_live_ready() -> bool:
        return (
            settings.instagram_provider not in {"mock", "replay"}
            and settings.instagram_live_enabled
            and settings.external_spend_unlocked
        )

    def radar_spend_allowed() -> bool:
        return master_live_ready() and ops_control.radar_live_armed()

    def openai_spend_allowed() -> bool:
        return (
            settings.openai_live_enabled
            and bool(settings.openai_api_key)
            and ops_control.openai_live_armed()
        )
    pricing_service = PricingConfigService(workflow.session_factory)
    fx_policy_service = FxPolicyService(workflow.session_factory)
    intelligence_challenge = LeadIntelligenceChallenge()
    quality_gates_service = IndependentQualityGatesService()

    templates.env.globals.update(
        lead_status_label=lambda value: label(LEAD_STATUS_LABELS, value),
        deal_status_label=lambda value: label(DEAL_STATUS_LABELS, value),
        intent_label=lambda value: label(INTENT_LABELS, value),
        product_label=lambda value: label(PRODUCT_LABELS, value, "Товар не определён"),
        ai_source_label=lambda value: label(AI_SOURCE_LABELS, value, "Источник не указан"),
        funnel_stage_label=lambda value: label(FUNNEL_STAGE_LABELS, value),
        urgency_label=lambda value: label(URGENCY_LABELS, value),
        purchase_horizon_label=lambda value: label(PURCHASE_HORIZON_LABELS, value),
        commercial_stage_label=lambda value: label(COMMERCIAL_STAGE_LABELS, value),
        export_eligibility_label=lambda value: label(EXPORT_ELIGIBILITY_LABELS, value),
        coverage_label=lambda value: label(COVERAGE_LABELS, value),
        event_label=lambda value: label(EVENT_LABELS, value),
        change_type_label=lambda value: label(CHANGE_TYPE_LABELS, value),
        run_status_label=lambda value: label(RUN_STATUS_LABELS, value),
        trigger_label=lambda value: label(TRIGGER_LABELS, value),
        competitor_category_label=lambda value: label(COMPETITOR_CATEGORY_LABELS, value),
        competitor_tier_label=lambda value: label(COMPETITOR_TIER_LABELS, value),
        notification_policy_label=lambda value: label(
            NOTIFICATION_POLICY_LABELS, value, "Общий режим системы"
        ),
        channel_label=lambda value: label(CHANNEL_LABELS, value, "Не указан"),
        qualification_field_label=lambda value: label(
            QUALIFICATION_FIELD_LABELS, value, str(value)
        ),
        buyer_role_label=lambda value: label(BUYER_ROLE_LABELS, value, "Не определено"),
        buyer_role_icon=lambda value: BUYER_ROLE_ICONS.get(
            str(value) if value else "UNKNOWN", "❓"
        ),
        audience_health_label=lambda value: label(AUDIENCE_HEALTH_LABELS, value),
        budget_status_label=lambda value: label(BUDGET_STATUS_LABELS, value),
        money=lambda value: f"{float(value or 0):,.0f}".replace(",", " "),
        safe_attr=lambda obj, name, default=None: getattr(obj, name, default),
        lead_is_off_catalog=lead_is_off_catalog,
        lead_next_action_overdue=lead_next_action_overdue,
        lead_quality_badge=lead_quality_badge,
    )
    templates.env.filters["display_dt"] = lambda value, fmt="%d.%m %H:%M": format_display_dt(
        value, fmt, timezone=settings.web_display_timezone
    )

    def local_manager_id() -> int:
        if settings.web_manager_id:
            return settings.web_manager_id
        if settings.telegram_admin_chat_ids:
            return settings.telegram_admin_chat_ids[0]
        return 1

    @app.middleware("http")
    async def protect_mini_app(request: Request, call_next):
        public_paths = {"/auth", "/api/auth/telegram", "/health", "/ready", "/sw.js"}
        if not settings.web_auth_enabled:
            request.state.manager_id = local_manager_id()
            request.state.web_role = WebRole.ADMIN
            request.state.csrf_token = ""
            if (
                request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
                and request.url.path.startswith("/api/")
                and not settings.web_manager_id
            ):
                logger.warning(
                    "Dev web: mutating %s %s rejected — WEB_MANAGER_ID is not set",
                    request.method.upper(),
                    request.url.path,
                )
                return JSONResponse(
                    {"ok": False, "detail": _DEV_MUTATION_FORBIDDEN_DETAIL},
                    status_code=403,
                )
            return await call_next(request)
        if request.url.path.startswith("/static/") or request.url.path in public_paths:
            return await call_next(request)
        session_token = request.cookies.get(auth.COOKIE_NAME)
        manager = auth.validate_session(session_token)
        if manager is None:
            if request.url.path.startswith("/api/"):
                return JSONResponse(
                    {"ok": False, "detail": "Нужно открыть Lead Radar через Telegram."},
                    status_code=401,
                )
            return templates.TemplateResponse(
                request=request,
                name="auth.html",
                context={"request": request, "settings": settings},
                status_code=401,
            )
        principal = auth.principal_for(manager)
        if principal is None:
            return JSONResponse(
                {"ok": False, "detail": "Доступ этого пользователя отозван."},
                status_code=401,
            )
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf_token = request.headers.get("X-CSRF-Token")
            if session_token is None or not auth.validate_csrf_token(session_token, csrf_token):
                return JSONResponse(
                    {"ok": False, "detail": "Запрос отклонён: неверный CSRF token."},
                    status_code=403,
                )
        if principal.role < required_role(request.method, request.url.path):
            return JSONResponse(
                {"ok": False, "detail": "Недостаточно прав для этого действия."},
                status_code=403,
            )
        request.state.manager_id = manager
        request.state.web_role = principal.role
        request.state.csrf_token = auth.create_csrf_token(session_token)
        return await call_next(request)

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://telegram.org https://unpkg.com; "
            "worker-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
        )
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.web_public_url.startswith("https://"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    def base_context(request: Request, **kwargs):
        snapshot = controller.snapshot()
        requested_vertical = request.query_params.get("vertical", "").upper()
        selected_vertical = (
            "ARTIFICIAL_RATTAN"
            if request.url.path.startswith("/rattan") or requested_vertical == "ARTIFICIAL_RATTAN"
            else "FURNITURE"
        )
        return {
            "request": request,
            "now": datetime.now().astimezone(),
            "snapshot": snapshot,
            "settings": settings,
            "active_path": request.url.path,
            "manager_id": getattr(request.state, "manager_id", local_manager_id()),
            "web_role": getattr(request.state, "web_role", WebRole.ADMIN).name,
            "csrf_token": getattr(request.state, "csrf_token", ""),
            "safe_mode": not radar_spend_allowed(),
            "search_paused": not settings.lead_search_enabled
            or (
                settings.instagram_provider not in {"mock", "replay"}
                and not ops_control.radar_live_armed()
            ),
            "ops": ops_control.snapshot(),
            "master_live_ready": master_live_ready(),
            "openai_spend_allowed": openai_spend_allowed(),
            "telegram_manager_count": len(settings.telegram_manager_chat_ids),
            "selected_vertical": selected_vertical,
            "ai_version_info": {
                "rules_version": settings.lead_analysis_version,
                "openai_prompt_version": BudgetedCachedOpenAIAnalyzer.PROMPT_VERSION,
                "openai_schema_version": BudgetedCachedOpenAIAnalyzer.SCHEMA_VERSION,
            },
            **kwargs,
        }

    def manager_id(request: Request) -> int:
        return int(getattr(request.state, "manager_id", local_manager_id()))

    def enforce_agent_rate_limit(request: Request) -> None:
        limit = agent_rate_limiter.check(manager_id(request))
        if limit.allowed:
            return
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много запросов к AI. Подождите {limit.retry_after_seconds} сек.",
            headers={"Retry-After": str(limit.retry_after_seconds)},
        )

    @app.get("/auth", response_class=HTMLResponse)
    async def auth_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="auth.html",
            context={"request": request, "settings": settings},
        )

    @app.post("/api/auth/telegram")
    async def telegram_auth(request: Request):
        payload = await request.json()
        try:
            user = auth.validate_init_data(str(payload.get("initData") or ""))
        except TelegramAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        response = JSONResponse({"ok": True, "user_id": user.id})
        response.set_cookie(
            auth.COOKIE_NAME,
            auth.create_session(user.id),
            httponly=True,
            secure=bool(settings.web_public_url.startswith("https://")),
            samesite="strict",
            max_age=7 * 86400,
        )
        return response

    @app.post("/logout")
    async def logout():
        response = RedirectResponse("/auth", status_code=303)
        response.delete_cookie(auth.COOKIE_NAME)
        return response

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        data = await queries.dashboard()
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=base_context(request, **data),
        )

    @app.get("/rattan", response_class=HTMLResponse)
    async def rattan_workspace(request: Request):
        data = await queries.rattan_workspace()
        return templates.TemplateResponse(
            request=request,
            name="rattan.html",
            context=base_context(request, **data),
        )

    @app.get("/radar", response_class=HTMLResponse)
    async def radar(
        request: Request,
        q: str = "",
        competitor: str = "",
        kind: str = "",
    ):
        rows = await queries.signals(q=q, competitor=competitor, kind=kind)
        competitors = await queries.competitors()
        overview = await queries.signal_overview()
        scan_budget = await _scan_preview_payload()
        recent_runs = await queries.monitor_runs(limit=1)
        radar_feed = await queries.radar_feed(limit=8)
        return templates.TemplateResponse(
            request=request,
            name="radar.html",
            context=base_context(
                request,
                rows=rows,
                q=q,
                competitor_filter=competitor,
                kind_filter=kind,
                competitors=competitors,
                overview=overview,
                scan_budget=scan_budget,
                last_run=recent_runs[0] if recent_runs else None,
                radar_feed=radar_feed,
            ),
        )

    @app.get("/leads", response_class=HTMLResponse)
    async def leads(
        request: Request,
        q: str = "",
        status: str = "",
        quality: str = "",
        view: str = "board",
    ):
        rows = await queries.leads(q=q, status=status, quality=quality)
        board_statuses = [
            "ANALYZING",
            "AI_PENDING",
            "NEW",
            "TAKEN",
            "CONTACTED",
            "QUALIFIED",
            "OFFER_SENT",
            "NEGOTIATION",
            "WON",
            "LOST",
        ]
        use_board = view == "board" and not status and quality not in {
            "not_lead",
            "off_catalog",
            "garbage",
            "hot",
        }
        events_by_lead: dict[int, list] = {}
        if use_board and rows:
            events_by_lead = await queries.lead_recent_events(
                [lead.id for lead, *_rest in rows],
                limit_per_lead=5,
            )
        # Группировка в Python: шаблон не делает O(stages×rows).
        rows_by_stage: dict[str, list] = {stage: [] for stage in board_statuses}
        for row in rows:
            stage = row[0].status.value
            if stage in rows_by_stage:
                rows_by_stage[stage].append(row)
        return templates.TemplateResponse(
            request=request,
            name="leads.html",
            context=base_context(
                request,
                rows=rows,
                rows_by_stage=rows_by_stage,
                q=q,
                status_filter=status,
                quality_filter=quality,
                view=view if use_board else "list",
                events_by_lead=events_by_lead,
                board_statuses=board_statuses,
            ),
        )

    @app.get("/api/leads/export.csv")
    async def export_leads_csv(
        q: str = "",
        status: str = "",
        quality: str = "",
    ):
        """CSV воронки: только публичные Instagram-поля, без телефонов/email."""
        rows = await queries.leads(q=q, status=status, quality=quality, limit=1000)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "lead_id",
                "username",
                "display_name",
                "competitor",
                "status",
                "score",
                "intent",
                "product",
                "comment",
                "created_at",
                "deal_status",
            ]
        )
        for lead, contact, comment, competitor, _post, deal in rows:
            writer.writerow(
                [
                    lead.id,
                    contact.username,
                    contact.display_name or "",
                    competitor.normalized_handle,
                    lead.status.value,
                    lead.lead_score,
                    lead.intent or "",
                    lead.product_category or "",
                    (comment.text or "").replace("\n", " ").strip()[:500],
                    lead.created_at.isoformat() if lead.created_at else "",
                    deal.status.value if deal is not None else "",
                ]
            )
        payload = buffer.getvalue()
        return StreamingResponse(
            iter([payload]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="leads-funnel.csv"'},
        )

    @app.get("/leads/{lead_id}", response_class=HTMLResponse)
    async def lead_detail(request: Request, lead_id: int):
        data = await queries.lead_detail(lead_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Лид не найден")
        commercial_competitors = {
            competitor.id
            for _comment, competitor, _post, history_lead in data["history"]
            if history_lead is not None
            and (history_lead.analysis_details or {}).get("commercial_quality")
            not in {None, "NON_COMMERCIAL"}
        }
        data["catalog_recommendation"] = await product_catalog_service.recommend_for_lead(
            data["lead"],
            commercial_competitor_count=len(commercial_competitors),
        )
        ranked_products, _quantity = await product_catalog_service.ranked_products_for_lead(
            data["lead"]
        )
        data["catalog_matches"] = ranked_products[:3]
        return templates.TemplateResponse(
            request=request,
            name="lead_detail.html",
            context=base_context(request, **data),
        )

    @app.get("/catalog", response_class=HTMLResponse)
    async def catalog(request: Request, vertical: str | None = None):
        products = await product_catalog_service.products(vertical=vertical)
        return templates.TemplateResponse(
            request=request,
            name="catalog.html",
            context=base_context(
                request,
                products=products,
                catalog_vertical=vertical or "ALL",
                product_categories=sorted(ALLOWED_PRODUCT_CATEGORIES),
            ),
        )

    @app.get("/contacts", response_class=HTMLResponse)
    async def contacts(request: Request, q: str = ""):
        rows = await queries.contacts(q=q)
        return templates.TemplateResponse(
            request=request,
            name="contacts.html",
            context=base_context(request, rows=rows, q=q),
        )

    @app.get("/contacts/{contact_id}", response_class=HTMLResponse)
    async def contact_detail(request: Request, contact_id: int):
        data = await queries.contact_detail(contact_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Клиент не найден")
        return templates.TemplateResponse(
            request=request,
            name="contact_detail.html",
            context=base_context(request, **data),
        )

    @app.get("/tasks", response_class=HTMLResponse)
    async def tasks(request: Request, view: str = "open", q: str = ""):
        rows = await queries.tasks(view=view, q=q)
        return templates.TemplateResponse(
            request=request,
            name="tasks.html",
            context=base_context(request, rows=rows, view=view, q=q),
        )

    @app.get("/deals", response_class=HTMLResponse)
    async def deals(request: Request, q: str = "", status: str = ""):
        rows = await queries.deals(q=q, status=status)
        return templates.TemplateResponse(
            request=request,
            name="deals.html",
            context=base_context(request, rows=rows, q=q, status_filter=status),
        )

    @app.get("/analytics", response_class=HTMLResponse)
    async def analytics(request: Request, days: int = 30):
        if days not in {1, 7, 30}:
            days = 30
        data = await queries.analytics(days=days)
        return templates.TemplateResponse(
            request=request,
            name="analytics.html",
            context=base_context(request, **data),
        )

    @app.get("/economics", response_class=HTMLResponse)
    async def economics(request: Request, days: int = 30):
        if days not in {1, 7, 30}:
            days = 30
        data = await queries.economics(days=days)
        scan_budget = await _scan_preview_payload()
        return templates.TemplateResponse(
            request=request,
            name="economics.html",
            context=base_context(request, scan_budget=scan_budget, **data),
        )

    @app.get("/api/economics/export.csv")
    async def export_economics_csv(days: int = 30):
        """CSV unit economics / OpenAI cost: только агрегаты из БД, без PII."""
        if days not in {1, 7, 30}:
            days = 30
        data = await queries.economics(days=days)
        page = data["page"]
        economics = data["economics"]
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["metric", "value", "unit", "period_days"])
        rows = [
            ("openai_events", page.openai.events, "count"),
            ("openai_known_spend_usd", page.openai.known_spend_usd, "usd"),
            ("openai_usd_per_lead", page.openai_usd_per_lead, "usd"),
            ("openai_usd_per_hot", page.openai_usd_per_hot, "usd"),
            ("signals_count", economics.signals_count, "count"),
            ("leads_count", economics.leads_count, "count"),
            ("hot_count", economics.hot_count, "count"),
            ("won_count", economics.won_count, "count"),
            ("known_spend_usd", economics.known_spend_usd, "usd"),
            ("cost_per_lead_usd", economics.cost_per_lead_usd, "usd"),
            ("cost_per_hot_usd", economics.cost_per_hot_usd, "usd"),
            ("revenue_uzs", economics.revenue_uzs, "uzs"),
            ("gross_profit_uzs", economics.gross_profit_uzs, "uzs"),
            ("roi_ratio", economics.roi_ratio, "ratio"),
            ("roi_status", economics.roi_status, "text"),
            ("credits_known", page.credits.known_credits, "credits"),
            ("credits_per_lead", page.credits.credits_per_lead, "credits"),
            ("credits_per_hot", page.credits.credits_per_hot, "credits"),
        ]
        for metric, value, unit in rows:
            writer.writerow([metric, "" if value is None else value, unit, days])
        payload = buffer.getvalue()
        return StreamingResponse(
            iter([payload]),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="economics-{days}d.csv"'
            },
        )

    @app.get("/audiences", response_class=HTMLResponse)
    async def audiences(request: Request, vertical: str = "FURNITURE"):
        rows = await queries.audiences(vertical=vertical)
        return templates.TemplateResponse(
            request=request,
            name="audiences.html",
            context=base_context(request, rows=rows),
        )

    @app.get("/audiences/quality", response_class=HTMLResponse)
    async def audience_quality(request: Request, vertical: str = "FURNITURE"):
        data = await queries.audience_quality(vertical=vertical)
        return templates.TemplateResponse(
            request=request,
            name="audience_quality.html",
            context=base_context(request, **data),
        )

    @app.get("/audiences/{slug}", response_class=HTMLResponse)
    async def audience_detail(request: Request, slug: str):
        facets = AudienceFacetQuery.from_mapping(request.query_params)
        data = await queries.audience_detail(slug, facets=facets)
        if data is None:
            raise HTTPException(status_code=404, detail="Аудитория не найдена")
        meta_readiness = await meta_audience_service.readiness(slug)
        from app.services.export_recipe_service import RECIPES

        export_recipe = next(
            (recipe for recipe in RECIPES.values() if recipe.segment_slug == slug),
            None,
        )
        return templates.TemplateResponse(
            request=request,
            name="audience_detail.html",
            context=base_context(
                request,
                meta_readiness=meta_readiness,
                export_recipe=export_recipe,
                **data,
            ),
        )

    @app.get("/competitors", response_class=HTMLResponse)
    async def competitors(request: Request):
        rows = await queries.competitors()
        overview = await queries.market_overview()
        intelligence_overview = await queries.competitor_intelligence_overview()
        overlaps = await queries.competitor_overlap_network()
        overlap_graph = await queries.competitor_overlap_graph()
        return templates.TemplateResponse(
            request=request,
            name="competitors.html",
            context=base_context(
                request,
                rows=rows,
                market_overview=overview,
                intelligence_overview=intelligence_overview,
                overlaps=overlaps,
                overlap_graph=overlap_graph,
                categories=COMPETITOR_CATEGORY_LABELS,
            ),
        )

    @app.get("/discovery", response_class=HTMLResponse)
    async def discovery(request: Request):
        data = await discovery_service.dashboard()
        return templates.TemplateResponse(
            request=request,
            name="discovery.html",
            context=base_context(
                request,
                **data,
                categories=COMPETITOR_CATEGORY_LABELS,
                discovery_status_labels={
                    "DISCOVERED": "Не проверено",
                    "REVIEWED": "Проверено",
                    "REJECTED": "Не подходит",
                },
                discovery_diff_labels={
                    "NEW": "Новая компания",
                    "UPDATED": "Данные изменились",
                    "PRICE_CHANGED": "Изменилась цена",
                    "STOCK_CHANGED": "Изменилось наличие",
                    "ROLE_CHANGED": "Изменился сегмент",
                },
            ),
        )

    @app.get("/competitors/compare", response_class=HTMLResponse)
    async def competitors_compare(request: Request):
        left_raw = request.query_params.get("left")
        right_raw = request.query_params.get("right")
        if not left_raw or not right_raw or not left_raw.isdigit() or not right_raw.isdigit():
            raise HTTPException(status_code=400, detail="Укажите left и right — ID конкурентов")
        data = await queries.competitor_compare(int(left_raw), int(right_raw))
        if data is None:
            raise HTTPException(status_code=404, detail="Один из конкурентов не найден")
        all_rows = await queries.competitors()
        return templates.TemplateResponse(
            request=request,
            name="competitor_compare.html",
            context=base_context(request, compare=data, competitor_options=all_rows),
        )

    @app.get("/competitors/{competitor_id}", response_class=HTMLResponse)
    async def competitor_detail(request: Request, competitor_id: int):
        data = await queries.competitor_intelligence(competitor_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Конкурент не найден")
        return templates.TemplateResponse(
            request=request,
            name="competitor_detail.html",
            context=base_context(request, **data),
        )

    @app.get("/openings", response_class=HTMLResponse)
    async def openings(request: Request):
        from app.services.place_opening_service import PlaceOpeningService

        service = PlaceOpeningService(workflow.session_factory)
        queue = await service.get_review_queue()
        return templates.TemplateResponse(
            request=request,
            name="openings.html",
            context=base_context(
                request,
                queue=queue,
            ),
        )

    @app.get("/roadmap", response_class=HTMLResponse)
    async def roadmap(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="roadmap.html",
            context=base_context(request, current_stage=3, total_stages=7),
        )

    @app.get("/system", response_class=HTMLResponse)
    async def system(request: Request):
        runs = await queries.monitor_runs()
        usage = await queries.usage_today()
        usage_breakdown = await usage_service.breakdown_today("instagram")
        instagram_remaining = max(
            0, settings.instagram_daily_request_limit - usage.get("instagram", 0)
        )
        scan_plan = await queries.scan_plan(
            max_units_per_scan=settings.instagram_max_units_per_scan,
            daily_remaining=instagram_remaining,
            live_enabled=radar_spend_allowed(),
        )
        replay_scenario = getattr(getattr(controller.monitor, "provider", None), "scenario", None)
        replay_status = replay_scenario.status() if replay_scenario is not None else None
        notification_readiness = await notification_readiness_service.preview(limit=10)
        uncertain_notifications = await queries.uncertain_notification_queue(limit=20)
        uncertain_budget_reservations = await queries.uncertain_external_reservation_queue(limit=20)
        ai_safety = await queries.ai_safety_diagnostics()
        intelligence_quality = intelligence_challenge.evaluate(
            hot_threshold=settings.hot_lead_threshold
        )
        quality_gates = quality_gates_service.snapshot(
            rules_version=settings.lead_analysis_version
        )
        manager_feedback_quality = await queries.manager_feedback_quality()
        feedback_learning_service = FeedbackLearningService(
            workflow.session_factory,
            hot_threshold=settings.hot_lead_threshold,
        )
        feedback_learning = await feedback_learning_service.snapshot(days=30)
        feedback_learning_rows = await feedback_learning_service.false_positive_rows(
            limit=10,
            days=30,
        )
        rules_reanalyze = await queries.rules_reanalyze_status(
            settings.lead_analysis_version
        )
        pricing_configs = await pricing_service.list_active()
        fx_policies = await fx_policy_service.list_active()
        notification_modes = {
            "ALL_NEW_COMMENTS": (
                "Каждый новый комментарий",
                "Менеджер сразу видит каждый новый уникальный сигнал. История и replay не уведомляют.",
            ),
            "COMMERCIAL_ONLY": (
                "Только покупательский интерес",
                "Уведомление появится после бесплатной первичной классификации.",
            ),
            "HOT_ONLY": (
                "Только горячие лиды",
                "Менеджер получает только сигналы, достигшие HOT-порога.",
            ),
        }
        notification_policy_info = notification_modes[settings.notification_policy]
        production_notifications = notification_readiness.controlled_pilot_ready
        if production_notifications:
            telegram_detail = "Production-уведомления включены"
        elif not settings.telegram_bot_token:
            telegram_detail = "Нет TELEGRAM_BOT_TOKEN"
        elif not notification_readiness.worker_active:
            telegram_detail = "Worker не запущен (нужен полный python -m app.main, не web-only)"
        elif not notification_readiness.delivery_allowed_by_config:
            telegram_detail = "Доставка заблокирована конфигурацией (replay/mock или kill switch)"
        elif notification_readiness.admin_target_count <= 0:
            telegram_detail = "Нет admin chat id для доставки"
        else:
            telegram_detail = "Реальная отправка сейчас не выполняется"
        from app.services.export_recipe_service import RECIPES

        export_recipes = list(RECIPES.values())
        integrations = {
            "Telegram": {
                "configured": bool(settings.telegram_bot_token),
                "enabled": production_notifications,
                "detail": telegram_detail,
            },
            "Локальный анализ": {
                "configured": True,
                "enabled": True,
                "detail": "Работает без токенов",
            },
            "OpenAI": {
                "configured": bool(settings.openai_api_key),
                "enabled": openai_spend_allowed(),
                "detail": f"{usage.get('openai', 0)}/{settings.openai_daily_request_limit} запросов сегодня",
            },
            "ScrapeCreators / Bright Data": {
                "configured": bool(settings.scrapecreators_api_key or settings.brightdata_api_key),
                "enabled": radar_spend_allowed(),
                "detail": f"{usage.get('instagram', 0)}/{settings.instagram_daily_request_limit} операций сегодня",
            },
            "AI Agent / MCP": {
                "configured": True,
                "enabled": True,
                "detail": (
                    "Read tools: DB-backed · Write: crm.assign_lead (approval) · "
                    f"Meta: {'live' if settings.meta_ads_live_enabled else 'NOT_CONNECTED'}"
                ),
            },
            "Meta / Google": {
                "configured": bool(settings.meta_ads_access_token and settings.meta_ads_ad_account_id),
                "enabled": settings.meta_ads_live_enabled,
                "detail": (
                    "Meta Ads live"
                    if settings.meta_ads_live_enabled
                    else "NOT_CONNECTED · Google openings — локальная БД"
                ),
            },
            "База данных": {"configured": True, "enabled": True, "detail": "Источник истины"},
        }
        return templates.TemplateResponse(
            request=request,
            name="system.html",
            context=base_context(
                request,
                runs=runs,
                integrations=integrations,
                usage=usage,
                usage_breakdown=usage_breakdown,
                scan_plan=scan_plan,
                replay_status=replay_status,
                notification_policy_info=notification_policy_info,
                notification_readiness=notification_readiness,
                uncertain_notifications=uncertain_notifications,
                uncertain_budget_reservations=uncertain_budget_reservations,
                ai_safety=ai_safety,
                intelligence_quality=intelligence_quality,
                quality_gates=quality_gates,
                manager_feedback_quality=manager_feedback_quality,
                feedback_learning=feedback_learning,
                feedback_learning_rows=feedback_learning_rows,
                rules_reanalyze=rules_reanalyze,
                pricing_configs=pricing_configs,
                fx_policies=fx_policies,
                export_recipes=export_recipes,
            ),
        )

    @app.post("/api/pricing")
    async def set_pricing(request: Request):
        data = await request.json()

        def optional_decimal(name: str) -> Decimal | None:
            value = str(data.get(name) or "").strip()
            if not value:
                return None
            try:
                parsed = Decimal(value)
            except InvalidOperation as exc:
                raise HTTPException(status_code=400, detail=f"Некорректная цена: {name}") from exc
            if parsed < 0:
                raise HTTPException(status_code=400, detail="Цена не может быть отрицательной")
            return parsed

        try:
            config = await pricing_service.set_price(
                provider=str(data.get("provider") or ""),
                operation=str(data.get("operation") or ""),
                model_name=str(data.get("model_name") or "") or None,
                pricing_basis=str(data.get("pricing_basis") or "UNIT"),
                unit_price=optional_decimal("unit_price"),
                input_price=optional_decimal("input_price"),
                output_price=optional_decimal("output_price"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "pricing_config_id": config.id,
            "message": "Новая версия цены сохранена; предыдущая осталась в истории.",
        }

    @app.post("/api/pricing/fx")
    async def set_fx_rate(request: Request):
        data = await request.json()
        try:
            rate = Decimal(str(data.get("rate") or ""))
            policy = await fx_policy_service.set_rate(
                base_currency=str(data.get("base_currency") or ""),
                quote_currency=str(data.get("quote_currency") or ""),
                rate=rate,
                manager_id=manager_id(request),
            )
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "fx_policy_id": policy.id,
            "message": "Новая версия FX-курса сохранена; история не изменена.",
        }

    @app.post("/api/replay/advance")
    async def replay_advance(request: Request):
        scenario = getattr(getattr(controller.monitor, "provider", None), "scenario", None)
        if scenario is None:
            raise HTTPException(status_code=409, detail="Replay-режим сейчас не включён")
        status = scenario.advance()
        return {
            "ok": True,
            "step": status.step,
            "message": f"Сценарий переключён: {status.title}. Теперь запустите проверку.",
        }

    @app.post("/api/replay/reset")
    async def replay_reset(request: Request):
        scenario = getattr(getattr(controller.monitor, "provider", None), "scenario", None)
        if scenario is None:
            raise HTTPException(status_code=409, detail="Replay-режим сейчас не включён")
        status = scenario.reset()
        return {
            "ok": True,
            "step": status.step,
            "message": f"Сценарий сброшен: {status.title}",
        }

    async def _scan_preview_payload(requested_credits: int | None = None) -> dict:
        daily = await usage_service.snapshot(
            "instagram", settings.instagram_daily_request_limit
        )
        policy = await provider_budget_service.policy(
            settings.instagram_provider,
            "instagram",
        )
        requested = (
            requested_credits
            if requested_credits is not None
            else ops_control.snapshot().default_scan_credits
            if ops_control.snapshot().default_scan_credits
            else policy.default_scan_budget_units
            if policy is not None
            else settings.instagram_max_units_per_scan
        )
        is_live = settings.instagram_provider not in {"mock", "replay"}
        availability = await provider_budget_service.available_for_scan(
            provider=settings.instagram_provider,
            requested_units=requested,
            daily_remaining=daily.remaining,
        )
        effective = availability.effective_units if is_live else 0
        plan = await queries.scan_plan(
            max_units_per_scan=effective,
            daily_remaining=daily.remaining,
            live_enabled=radar_spend_allowed(),
        )
        budget = await provider_budget_service.snapshot(settings.instagram_provider)
        blocking_reasons = list(availability.blocking_reasons) if is_live else []
        if not settings.lead_search_enabled:
            blocking_reasons.append("Поиск лидов приостановлен.")
        if is_live and not settings.instagram_live_enabled:
            blocking_reasons.append("Live-вызовы Instagram отключены в .env (master).")
        if is_live and not settings.external_spend_unlocked:
            blocking_reasons.append(
                "Master unlock не активен: EXTERNAL_KILL_SWITCH / EXTERNAL_LIVE_UNLOCK."
            )
        if is_live and not ops_control.radar_live_armed():
            blocking_reasons.append(
                "Live Radar выключен в системе. Включите тумблер на странице System или Radar."
            )
        return {
            "ok": True,
            "search_enabled": settings.lead_search_enabled and (
                not is_live or ops_control.radar_live_armed()
            ),
            "is_live": is_live,
            "provider": settings.instagram_provider,
            "live_enabled": radar_spend_allowed(),
            "radar_live_armed": ops_control.radar_live_armed(),
            "openai_live_armed": ops_control.openai_live_armed(),
            "master_live_ready": master_live_ready(),
            "requires_confirmation": is_live,
            "requested_credits": requested,
            "effective_max_credits": effective if radar_spend_allowed() else 0,
            "credits_remaining": availability.provider_balance,
            "credits_remaining_source": availability.provider_balance_source,
            "used_today": daily.used_today,
            "daily_remaining": daily.remaining,
            "used_this_month": budget.used_this_month if budget is not None else 0,
            "monthly_target": budget.monthly_target if budget is not None else None,
            "monthly_soft_limit": (
                budget.monthly_soft_limit if budget is not None else None
            ),
            "monthly_hard_limit": (
                budget.monthly_hard_limit if budget is not None else None
            ),
            "monthly_remaining": availability.monthly_remaining,
            "default_scan_budget": (
                ops_control.snapshot().default_scan_credits
                if ops_control.snapshot().default_scan_credits
                else (
                    policy.default_scan_budget_units if policy is not None else None
                )
            ),
            "maximum_manual_scan_budget": (
                policy.maximum_manual_scan_budget_units if policy is not None else None
            ),
            "average_daily_burn_7d": (
                budget.average_daily_burn_7d if budget is not None else 0
            ),
            "average_daily_burn_30d": (
                budget.average_daily_burn_30d if budget is not None else 0
            ),
            "projected_monthly_burn": (
                budget.projected_monthly_burn if budget is not None else 0
            ),
            "package_months_remaining_estimate": (
                budget.months_remaining if budget is not None else None
            ),
            "package_months_remaining_at_target": (
                budget.months_remaining_at_target if budget is not None else None
            ),
            "budget_status": budget.budget_status if budget is not None else "NOT_CONFIGURED",
            "active_competitors": plan["active_competitors"],
            "due_competitors": plan["due_competitors"],
            "estimated_competitors_reachable": min(
                plan["active_competitors"], effective
            ),
            "estimated_comment_pages": max(
                0, effective - min(plan["active_competitors"], effective)
            ),
            "expected_min_units": plan.get("expected_min_units"),
            "comment_candidates": plan.get("comment_candidates"),
            "clamped": bool(
                is_live and requested > effective and radar_spend_allowed()
            ),
            "month_credits_low": bool(
                budget is not None and getattr(budget, "month_credits_low", False)
            ),
            "can_start": not blocking_reasons and (effective > 0 or not is_live),
            "blocking_reasons": blocking_reasons,
            "plan": plan,
        }

    @app.get("/api/scan/preview")
    async def scan_preview(request: Request):
        raw = request.query_params.get("max_credits")
        try:
            requested = int(raw) if raw is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="max_credits должен быть целым") from exc
        return await _scan_preview_payload(requested)

    @app.post("/api/scan")
    async def scan_now(request: Request):
        if not settings.lead_search_enabled:
            raise HTTPException(
                status_code=409,
                detail="Поиск лидов временно приостановлен. ScrapeCreators credits не расходуются.",
            )
        payload = await _json_or_form(request)
        try:
            requested_credits = int(payload.get("max_credits") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="max_credits должен быть целым") from exc
        is_live = settings.instagram_provider not in {"mock", "replay"}
        if is_live:
            await ops_control.load()
        if is_live and not radar_spend_allowed():
            raise HTTPException(
                status_code=409,
                detail=(
                    "Live Radar выключен. Включите тумблер в системе "
                    "(и убедитесь, что master unlock в .env активен)."
                ),
            )
        if is_live and payload.get("confirm_live") is not True:
            raise HTTPException(
                status_code=428,
                detail="Live-проверка требует отдельного подтверждения расхода.",
            )
        preview = await _scan_preview_payload(requested_credits)
        if is_live and not preview["can_start"]:
            raise HTTPException(
                status_code=409,
                detail=" ".join(preview["blocking_reasons"]),
            )
        started = controller.start_cycle(
            "web",
            max_units=preview["effective_max_credits"] if is_live else None,
            requested_units=requested_credits if is_live else None,
        )
        return JSONResponse(
            {
                "ok": started,
                "message": "Проверка запущена" if started else "Проверка уже выполняется",
                "requested_credits": requested_credits,
                "effective_max_credits": preview["effective_max_credits"],
            }
        )

    @app.post("/api/ops/radar-live")
    async def set_radar_live(request: Request):
        if not master_live_ready():
            raise HTTPException(
                status_code=409,
                detail=(
                    "Master unlock не готов: нужен INSTAGRAM_PROVIDER=scrapecreators, "
                    "INSTAGRAM_LIVE_CALLS_ENABLED=true, EXTERNAL_KILL_SWITCH=false, "
                    "EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS."
                ),
            )
        payload = await _json_or_form(request)
        armed = str(payload.get("armed", "")).lower() in {"1", "true", "yes", "on"}
        credits = payload.get("default_scan_credits")
        try:
            default_credits = int(credits) if credits not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="default_scan_credits должен быть целым"
            ) from exc
        snap = await ops_control.set_radar_live(
            armed,
            manager_id=manager_id(request),
            default_scan_credits=default_credits,
        )
        return {
            "ok": True,
            "radar_live_armed": snap.radar_live_armed,
            "openai_live_armed": snap.openai_live_armed,
            "default_scan_credits": snap.default_scan_credits,
            "message": (
                "Live Radar включён. Можно запускать проверку с лимитом credits."
                if snap.radar_live_armed
                else "Live Radar выключен. Внешние Instagram-запросы заблокированы."
            ),
        }

    @app.post("/api/ops/openai-live")
    async def set_openai_live(request: Request):
        if not settings.openai_live_enabled:
            raise HTTPException(
                status_code=409,
                detail=(
                    "OpenAI master выключен в .env (OPENAI_LIVE_CALLS_ENABLED / unlock). "
                    "Сначала включите master, затем тумблер в системе."
                ),
            )
        if not settings.openai_api_key:
            raise HTTPException(status_code=409, detail="OPENAI_API_KEY не задан.")
        payload = await _json_or_form(request)
        armed = str(payload.get("armed", "")).lower() in {"1", "true", "yes", "on"}
        if armed:
            gates = quality_gates_service.snapshot(
                rules_version=settings.lead_analysis_version
            )
            allowed, reason = gates.openai_live_allowed()
            if not allowed:
                raise HTTPException(status_code=409, detail=reason)
        snap = await ops_control.set_openai_live(armed, manager_id=manager_id(request))
        return {
            "ok": True,
            "openai_live_armed": snap.openai_live_armed,
            "radar_live_armed": snap.radar_live_armed,
            "message": (
                "OpenAI анализ включён для неоднозначных лидов (hybrid)."
                if snap.openai_live_armed
                else "OpenAI анализ выключен. Работают только локальные правила."
            ),
        }

    @app.post("/api/ops/ai-concurrency")
    async def set_ai_concurrency(request: Request):
        payload = await _json_or_form(request)
        try:
            max_concurrency = int(payload.get("max_concurrency") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="max_concurrency должен быть целым от 1 до 10"
            ) from exc
        snap = await ops_control.set_ai_analysis_concurrency(
            max_concurrency,
            manager_id=manager_id(request),
        )
        if analysis_pipeline is not None:
            await analysis_pipeline.set_max_concurrency(snap.ai_analysis_max_concurrency)
        return {
            "ok": True,
            "ai_analysis_max_concurrency": snap.ai_analysis_max_concurrency,
            "message": (
                f"Параллельных OpenAI-разборов: {snap.ai_analysis_max_concurrency}. "
                "Применено сразу."
            ),
        }

    @app.post("/api/notifications/uncertain/{kind}/{log_id}/resolve")
    async def resolve_uncertain_notification(
        request: Request,
        kind: str,
        log_id: int,
    ):
        payload = await _json_or_form(request)
        delivered_raw = str(payload.get("delivered", "")).strip().lower()
        if delivered_raw not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
            raise HTTPException(
                status_code=400,
                detail="Укажите delivered=true (уже в Telegram) или delivered=false (вернуть в очередь)",
            )
        delivered = delivered_raw in {"1", "true", "yes", "on"}
        message_id_raw = payload.get("message_id")
        message_id = None
        if message_id_raw not in (None, ""):
            try:
                message_id = int(message_id_raw)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=400, detail="message_id должен быть целым"
                ) from exc
        kind_norm = kind.strip().lower()
        if kind_norm == "lead":
            ok = await resolve_uncertain_lead_log(
                workflow.session_factory,
                log_id,
                delivered=delivered,
                message_id=message_id,
            )
        elif kind_norm == "change":
            ok = await resolve_uncertain_change_log(
                workflow.session_factory,
                log_id,
                delivered=delivered,
                message_id=message_id,
            )
        else:
            raise HTTPException(status_code=404, detail="Тип сверки: lead или change")
        if not ok:
            raise HTTPException(
                status_code=409,
                detail="Запись не найдена или уже не в статусе UNCERTAIN",
            )
        return {
            "ok": True,
            "kind": kind_norm,
            "log_id": log_id,
            "delivered": delivered,
            "message": (
                "Отмечено как доставлено в Telegram"
                if delivered
                else "Возвращено в очередь на повторную отправку"
            ),
        }

    @app.post("/api/budget/reservations/{reservation_id}/reconcile")
    async def reconcile_budget_reservation(request: Request, reservation_id: int):
        payload = await _json_or_form(request)
        spent_raw = str(payload.get("spent", "")).strip().lower()
        if spent_raw not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
            raise HTTPException(
                status_code=400,
                detail="Укажите spent=true (провайдер списал) или spent=false (не списал)",
            )
        spent = spent_raw in {"1", "true", "yes", "on"}
        units_raw = payload.get("units")
        units = None
        if units_raw not in (None, ""):
            try:
                units = max(0, int(units_raw))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="units должен быть целым") from exc
        ok = await usage_service.reconcile_uncertain_reservation(
            reservation_id,
            spent=spent,
            units=units,
        )
        if not ok:
            raise HTTPException(
                status_code=409,
                detail="Резервация не найдена или уже не в статусе UNCERTAIN",
            )
        return {
            "ok": True,
            "reservation_id": reservation_id,
            "spent": spent,
            "message": (
                "Списание подтверждено и зафиксировано в ledger"
                if spent
                else "Резервация закрыта без списания"
            ),
        }

    @app.post("/api/signals/review-all")
    async def review_all_signals(request: Request):
        """Одна кнопка: свежие комментарии → лиды по правилам → очередь GPT для спорных."""
        payload = await _json_or_form(request)
        limit = max(1, min(int(payload.get("limit") or 100), 500))
        gpt_limit = max(1, min(int(payload.get("gpt_limit") or 10), 50))
        results = await local_lead_service.backfill_unanalyzed_comments(limit)
        rules_pending = sum(item.status == LeadStatus.AI_PENDING for item in results)
        gpt_queued = 0
        gpt_processed = 0
        use_openai = openai_spend_allowed()
        if use_openai:
            if analysis_pipeline is not None:
                gpt_queued = await analysis_pipeline.enqueue_retry_batch(
                    gpt_limit, cooldown_seconds=0
                )
            else:
                retry_results = await hybrid_lead_service.retry_pending(
                    gpt_limit, cooldown_seconds=0
                )
                gpt_processed = len(retry_results)
        parts: list[str] = []
        if results:
            parts.append(f"Оценено комментариев: {len(results)}")
        else:
            parts.append("Свежих комментариев без оценки не осталось")
        if rules_pending:
            parts.append(f"спорных после правил: {rules_pending}")
        if use_openai:
            if gpt_queued:
                parts.append(f"в очередь GPT: {gpt_queued}")
            elif gpt_processed:
                parts.append(f"GPT дожал: {gpt_processed}")
        elif rules_pending:
            parts.append("включите OpenAI для GPT-оценки спорных")
        return {
            "ok": True,
            "processed": len(results),
            "rules_pending": rules_pending,
            "gpt_queued": gpt_queued,
            "gpt_processed": gpt_processed,
            "openai_used": use_openai,
            "async": bool(gpt_queued),
            "message": ". ".join(parts) + ".",
        }

    @app.post("/api/history/analyze-local")
    async def analyze_history_local(request: Request):
        payload = await _json_or_form(request)
        limit = max(1, min(int(payload.get("limit") or 100), 500))
        results = await local_lead_service.backfill_unanalyzed_comments(limit)
        pending = sum(item.status == LeadStatus.AI_PENDING for item in results)
        return {
            "ok": True,
            "processed": len(results),
            "pending": pending,
            "message": (
                f"Оценено комментариев: {len(results)}. "
                f"Спорных (нужен GPT): {pending}. OpenAI не вызывался."
            ),
        }

    @app.post("/api/leads/retry-pending")
    async def retry_pending_leads(request: Request):
        payload = await _json_or_form(request)
        limit = max(1, min(int(payload.get("limit") or 10), 50))
        use_openai = openai_spend_allowed()
        if analysis_pipeline is not None and use_openai:
            queued = await analysis_pipeline.enqueue_retry_batch(limit, cooldown_seconds=0)
            return {
                "ok": True,
                "queued": queued,
                "async": True,
                "openai_used": True,
                "message": (
                    f"В очередь GPT поставлено: {queued}. "
                    "Оценка идёт в фоне — обновите Радар через минуту."
                ),
            }
        service = hybrid_lead_service if use_openai else local_lead_service
        results = await service.retry_pending(limit, cooldown_seconds=0)
        still_pending = sum(item.status == LeadStatus.AI_PENDING for item in results)
        if use_openai:
            message = (
                f"Умный разбор: обработано {len(results)}. "
                f"Ещё ждут GPT: {still_pending}."
            )
        else:
            message = (
                f"Только правила: обработано {len(results)}. "
                f"Спорных осталось: {still_pending}. "
                "Включите OpenAI на Радаре для GPT-оценки."
            )
        return {
            "ok": True,
            "processed": len(results),
            "still_pending": still_pending,
            "openai_used": use_openai,
            "async": False,
            "message": message,
        }

    @app.post("/api/leads/reanalyze-batch")
    async def reanalyze_leads_batch(request: Request):
        """Переоценить свежие лиды NEW/AI_PENDING или спорные NOT_LEAD новыми правилами + GPT."""
        payload = await _json_or_form(request)
        limit = max(1, min(int(payload.get("limit") or 25), 100))
        include_not_lead = payload.get("include_not_lead_high_score") in {
            True,
            "true",
            "1",
        }
        min_not_lead_score = max(0, min(int(payload.get("min_not_lead_score") or 50), 100))
        use_openai = openai_spend_allowed()
        service = hybrid_lead_service if use_openai else local_lead_service
        results = await service.reanalyze_batch(
            limit,
            include_not_lead_high_score=include_not_lead,
            min_not_lead_score=min_not_lead_score,
        )
        not_lead = sum(item.status == LeadStatus.NOT_LEAD for item in results)
        pending = sum(item.status == LeadStatus.AI_PENDING for item in results)
        new_leads = sum(item.status == LeadStatus.NEW for item in results)
        scope = "NEW/AI_PENDING"
        if include_not_lead:
            scope += f" + NOT_LEAD≥{min_not_lead_score}"
        return {
            "ok": True,
            "processed": len(results),
            "not_lead": not_lead,
            "still_new": new_leads,
            "pending": pending,
            "openai_used": use_openai,
            "include_not_lead_high_score": include_not_lead,
            "rules_version": settings.lead_analysis_version,
            "message": (
                f"Переоценено ({scope}, правила {settings.lead_analysis_version}): {len(results)}"
                f" · лидов: {new_leads} · не лид: {not_lead}"
                + (f" · ждут GPT: {pending}" if pending else "")
            ),
        }

    @app.get("/api/system/feedback-export")
    async def feedback_export():
        """Экспорт HOT false-positive кейсов для offline eval."""
        service = FeedbackLearningService(
            workflow.session_factory,
            hot_threshold=settings.hot_lead_threshold,
        )
        return {
            "rules_version": settings.lead_analysis_version,
            "cases": await service.export_cases(limit=50, days=30),
        }

    @app.post("/api/leads/bulk-action")
    async def bulk_lead_action(request: Request):
        """Массово взять NEW или отметить NOT_LEAD по списку id (до 50)."""
        payload = await _json_or_form(request)
        action = str(payload.get("action") or "").strip().lower().replace("-", "_")
        raw_ids = payload.get("lead_ids")
        if action not in {"take", "not_lead"}:
            raise HTTPException(status_code=400, detail="Допустимы action=take или action=not_lead")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise HTTPException(status_code=400, detail="Нужен непустой список lead_ids")
        lead_ids = [int(item) for item in raw_ids[:50]]
        mgr = manager_id(request)
        processed = 0
        skipped = 0
        for lead_id in lead_ids:
            try:
                if action == "take":
                    await workflow.assign_manager(lead_id, mgr)
                else:
                    await workflow.mark_not_lead(lead_id, mgr)
                processed += 1
            except LeadWorkflowError:
                skipped += 1
        verb = "взято" if action == "take" else "не лид"
        return {
            "ok": True,
            "processed": processed,
            "skipped": skipped,
            "message": f"Сохранено · {verb}: {processed}" + (f" · пропущено: {skipped}" if skipped else ""),
        }

    @app.post("/api/leads/{lead_id}/follow-up")
    async def schedule_lead_follow_up(request: Request, lead_id: int):
        """One-click задача: связаться через N часов (по умолчанию 24)."""
        if crm is None:
            raise HTTPException(status_code=503, detail="CRM недоступен")
        payload = await _json_or_form(request)
        hours = max(1, min(int(payload.get("hours") or 24), 168))
        note = str(payload.get("note") or "Связаться с клиентом").strip() or "Связаться с клиентом"
        async with queries.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise HTTPException(status_code=404, detail="Лид не найден")
            contact_id = lead.contact_id
        due_at = datetime.now(UTC) + timedelta(hours=hours)
        try:
            task = await crm.schedule_contact(
                contact_id,
                manager_id(request),
                due_at=due_at,
                note=note,
                lead_id=lead_id,
            )
            return {
                "ok": True,
                "task_id": task.id,
                "message": f"Сохранено · напоминание через {hours} ч",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/leads/{lead_id}/analyze")
    async def analyze_lead_now(request: Request, lead_id: int):
        """Разбор NEW/AI_PENDING/ANALYZING: hybrid+OpenAI если armed, иначе только правила."""
        use_openai = openai_spend_allowed()
        async with workflow.session_factory() as session:
            lead = await session.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Лид не найден")
        if lead.status not in {
            LeadStatus.NEW,
            LeadStatus.AI_PENDING,
            LeadStatus.ANALYZING,
        }:
            raise HTTPException(
                status_code=409,
                detail=f"Разбор недоступен в статусе {lead.status.value}",
            )
        if analysis_pipeline is not None and use_openai:
            await analysis_pipeline.enqueue(lead_id)
            return {
                "ok": True,
                "lead_id": lead_id,
                "queued": True,
                "async": True,
                "openai_used": True,
                "message": "Лид поставлен в очередь OpenAI · разбор в фоне",
            }
        service = hybrid_lead_service if use_openai else local_lead_service
        result = await service.analyze_lead(lead_id)
        return {
            "ok": True,
            "lead_id": result.lead_id,
            "status": result.status.value,
            "score": result.score,
            "openai_used": use_openai,
            "message": (
                f"Разбор завершён · {result.status.value} · {result.score}/100"
                + (" · OpenAI/hybrid" if use_openai else " · только локальные правила")
            ),
        }

    @app.post("/api/leads/{lead_id}/take")
    async def take_lead(request: Request, lead_id: int):
        try:
            lead = await workflow.assign_manager(lead_id, manager_id(request))
            status_label = label(LEAD_STATUS_LABELS, lead.status)
            return {
                "ok": True,
                "status": lead.status.value,
                "message": f"Сохранено · {status_label}",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/leads/{lead_id}/assign")
    async def assign_lead(request: Request, lead_id: int):
        """Назначение/переназначение менеджера из карточки лида (список admin chat ids)."""
        payload = await _json_or_form(request)
        target = _int_or_none(payload.get("manager_id"))
        if target is None:
            target = manager_id(request)
        if target <= 0:
            raise HTTPException(status_code=400, detail="Некорректный manager_id")
        allowed = list(settings.telegram_admin_chat_ids)
        if allowed and target not in allowed:
            raise HTTPException(
                status_code=400,
                detail="Менеджер не в списке telegram_admin_chat_ids",
            )
        reassign = str(payload.get("reassign") or "").lower() in {"1", "true", "yes"}
        try:
            lead = await workflow.assign_manager(lead_id, target, reassign=reassign)
            status_label = label(LEAD_STATUS_LABELS, lead.status)
            return {
                "ok": True,
                "status": lead.status.value,
                "assigned_manager_telegram_id": lead.assigned_manager_telegram_id,
                "message": f"Ответственный · {target} · {status_label}",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/leads/{lead_id}/not-lead")
    async def not_lead(request: Request, lead_id: int):
        try:
            lead = await workflow.mark_not_lead(lead_id, manager_id(request))
            status_label = label(LEAD_STATUS_LABELS, lead.status)
            return {
                "ok": True,
                "status": lead.status.value,
                "message": f"Сохранено · {status_label}",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/leads/{lead_id}/stage")
    async def move_lead(request: Request, lead_id: int):
        payload = await _json_or_form(request)
        try:
            target = LeadStatus(str(payload.get("status") or "").upper())
            lead = await crm.move_lead(lead_id, manager_id(request), target)
            status_label = label(LEAD_STATUS_LABELS, lead.status)
            return {
                "ok": True,
                "status": lead.status.value,
                "message": f"Сохранено · {status_label}",
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Неизвестная стадия лида") from exc
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/contacts/{contact_id}/notes")
    async def add_note(request: Request, contact_id: int):
        payload = await _json_or_form(request)
        try:
            await crm.add_note(contact_id, manager_id(request), str(payload.get("text") or ""))
            return {"ok": True, "message": "Заметка сохранена"}
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/contacts/{contact_id}/qualification")
    async def update_qualification(request: Request, contact_id: int):
        payload = await _json_or_form(request)
        try:
            contact = await crm.update_contact_qualification(
                contact_id,
                manager_id(request),
                phone=str(payload.get("phone") or ""),
                preferred_channel=str(payload.get("preferred_channel") or ""),
                city=str(payload.get("city") or ""),
                interest_summary=str(payload.get("interest_summary") or ""),
                desired_quantity=_int_or_none(payload.get("desired_quantity")),
                budget_from=_decimal_or_none(payload.get("budget_from")),
                budget_to=_decimal_or_none(payload.get("budget_to")),
                desired_color=str(payload.get("desired_color") or ""),
                purchase_timeline=str(payload.get("purchase_timeline") or ""),
                qualification_note=str(payload.get("qualification_note") or ""),
            )
            return {
                "ok": True,
                "contact_id": contact.id,
                "message": "Информация о клиенте сохранена",
            }
        except (LeadWorkflowError, InvalidOperation, ValueError) as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/contacts/{contact_id}/reply")
    async def customer_reply(request: Request, contact_id: int):
        payload = await _json_or_form(request)
        lead_id = _int_or_none(payload.get("lead_id"))
        try:
            await crm.record_customer_reply(
                contact_id,
                manager_id(request),
                text=str(payload.get("text") or ""),
                lead_id=lead_id,
            )
            return {"ok": True, "message": "Ответ клиента добавлен в историю"}
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/contacts/{contact_id}/tasks")
    async def add_task(request: Request, contact_id: int):
        payload = await _json_or_form(request)
        try:
            due_at = parse_display_dt(
                str(payload.get("due_at") or ""),
                timezone=settings.web_display_timezone,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Укажите дату и время следующего контакта"
            ) from exc
        lead_id_raw = payload.get("lead_id")
        lead_id = int(lead_id_raw) if lead_id_raw not in (None, "") else None
        try:
            await crm.schedule_contact(
                contact_id,
                manager_id(request),
                due_at=due_at,
                note=str(payload.get("note") or ""),
                lead_id=lead_id,
            )
            return {"ok": True, "message": "Запланирован следующий контакт"}
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.get("/api/audiences/export-recipes")
    async def list_export_recipes():
        from app.services.export_recipe_service import RECIPES, CatalogMapper

        return {
            "ok": True,
            "recipes": [
                {
                    "slug": r.slug,
                    "name": r.name,
                    "description": r.description,
                    "meta_category": CatalogMapper.get_meta_category(r.product_category),
                }
                for r in RECIPES.values()
            ],
        }

    @app.post("/api/audiences/export-recipes/{recipe_slug}")
    async def run_export_recipe_endpoint(request: Request, recipe_slug: str):
        payload = await _json_or_form(request)
        dry_run = str(payload.get("dry_run", "true")).lower() in ("true", "1", "yes")
        export_service = ExportRecipeService(workflow.session_factory)
        try:
            res = await export_service.run_export_recipe(
                recipe_slug, dry_run=dry_run, manager_id=manager_id(request)
            )
            return {"ok": True, **res}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/openings")
    async def list_openings_review_queue():
        from app.services.place_opening_service import PlaceOpeningService

        service = PlaceOpeningService(workflow.session_factory)
        queue = await service.get_review_queue()
        return {
            "ok": True,
            "queue": [
                {
                    "id": item.id,
                    "place_name": item.place_name,
                    "place_type": item.place_type,
                    "city": item.city,
                    "opening_timeline": item.opening_timeline,
                    "confidence": item.confidence,
                    "review_status": item.review_status,
                    "contact_id": item.contact_id,
                }
                for item in queue
            ],
        }

    @app.post("/api/openings/{opening_id}/review")
    async def review_opening_endpoint(request: Request, opening_id: int):
        from app.services.place_opening_service import PlaceOpeningService

        payload = await _json_or_form(request)
        decision = str(payload.get("decision") or "").strip()
        service = PlaceOpeningService(workflow.session_factory)
        try:
            signal = await service.review_opening_signal(opening_id, manager_id(request), decision)
            return {
                "ok": True,
                "opening_id": signal.id,
                "review_status": signal.review_status,
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/agent/query")
    async def agent_query_endpoint(request: Request):
        from app.services.agent_session_service import AgentSessionService

        enforce_agent_rate_limit(request)
        payload = await _json_or_form(request)
        query = str(payload.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="query is required")
        session_id_raw = payload.get("session_id")
        if session_id_raw not in (None, ""):
            from app.services.agent_chat_orchestrator import AgentChatOrchestrator

            orchestrator = AgentChatOrchestrator(
                workflow.session_factory,
                hot_threshold=settings.hot_lead_threshold,
            )
            try:
                turn = await orchestrator.chat_turn(
                    manager_id(request),
                    query,
                    session_id=_optional_int(session_id_raw, field="session_id"),
                    context=payload,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {
                "session_id": turn.session_id,
                "message_id": turn.assistant_message_id,
                "query": turn.query,
                "answer": turn.answer,
                "evidence_ids": list(turn.evidence_ids),
                "grounded": turn.grounded,
                "synthesis_mode": turn.synthesis_mode,
                "pending_action": turn.pending_action,
                "tool_calls": list(turn.tool_calls),
            }
        service = AgentSessionService(
            workflow.session_factory,
            hot_threshold=settings.hot_lead_threshold,
        )
        try:
            result = await service.query(query, context=payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "query": result.query,
            "answer": result.answer,
            "evidence_ids": list(result.evidence_ids),
            "grounded": result.grounded,
            "synthesis_mode": result.synthesis_mode,
            "tool_calls": [
                {
                    "tool_name": item.tool_name,
                    "arguments": item.arguments,
                    "success": item.result.success,
                    "output": item.result.output,
                }
                for item in result.tool_calls
            ],
        }

    @app.get("/agent", response_class=HTMLResponse)
    async def agent_workspace(request: Request):
        lead_id_raw = request.query_params.get("lead_id")
        contact_id_raw = request.query_params.get("contact_id")
        agent_lead_id = int(lead_id_raw) if lead_id_raw and lead_id_raw.isdigit() else None
        agent_contact_id = (
            int(contact_id_raw) if contact_id_raw and contact_id_raw.isdigit() else None
        )
        if agent_lead_id is not None and agent_contact_id is None:
            async with workflow.session_factory() as session:
                lead = await session.get(Lead, agent_lead_id)
                if lead is not None:
                    agent_contact_id = lead.contact_id
        return templates.TemplateResponse(
            request=request,
            name="agent.html",
            context=base_context(
                request,
                agent_lead_id=agent_lead_id,
                agent_contact_id=agent_contact_id,
            ),
        )

    @app.get("/api/agent/sessions")
    async def agent_sessions_list(request: Request):
        from app.services.agent_chat_service import AgentChatService

        rows = await AgentChatService(workflow.session_factory).list_sessions(
            manager_id(request),
            limit=30,
        )
        return {
            "sessions": [
                {
                    "id": row.id,
                    "title": row.title,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ]
        }

    @app.post("/api/agent/sessions")
    async def agent_sessions_create(request: Request):
        from app.services.agent_chat_service import AgentChatService

        payload = await _json_or_form(request)
        row = await AgentChatService(workflow.session_factory).create_session(
            manager_id(request),
            title=str(payload.get("title") or "Новый чат"),
            context=payload,
        )
        return {"ok": True, "session_id": row.id, "title": row.title}

    @app.get("/api/agent/sessions/{session_id}/messages")
    async def agent_session_messages(request: Request, session_id: int):
        from app.services.agent_chat_service import AgentChatService

        chat = AgentChatService(workflow.session_factory)
        session = await chat.get_session(session_id)
        if session is None or session.manager_telegram_id != manager_id(request):
            raise HTTPException(status_code=404, detail="session not found")
        rows = await chat.list_messages(session_id, limit=200)
        return {
            "messages": [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content,
                    "pending_action": row.pending_action_json,
                    "pending_status": row.pending_status,
                    "tool_calls": row.tool_calls_json,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }

    @app.post("/api/agent/chat")
    async def agent_chat_turn(request: Request):
        from app.services.agent_chat_orchestrator import AgentChatOrchestrator

        enforce_agent_rate_limit(request)
        payload = await _json_or_form(request)
        query = str(payload.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="query is required")
        session_id = payload.get("session_id")
        orchestrator = AgentChatOrchestrator(
            workflow.session_factory,
            hot_threshold=settings.hot_lead_threshold,
        )
        try:
            turn = await orchestrator.chat_turn(
                manager_id(request),
                query,
                session_id=_optional_int(session_id, field="session_id"),
                context=payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "session_id": turn.session_id,
            "message_id": turn.assistant_message_id,
            "query": turn.query,
            "answer": turn.answer,
            "evidence_ids": list(turn.evidence_ids),
            "grounded": turn.grounded,
            "synthesis_mode": turn.synthesis_mode,
            "pending_action": turn.pending_action,
            "tool_calls": list(turn.tool_calls),
        }

    @app.post("/api/agent/approve")
    async def agent_approve_action(request: Request):
        from app.services.agent_chat_orchestrator import AgentChatOrchestrator

        payload = await _json_or_form(request)
        message_id = _required_positive_int(payload.get("message_id"), field="message_id")
        orchestrator = AgentChatOrchestrator(
            workflow.session_factory,
            hot_threshold=settings.hot_lead_threshold,
        )
        try:
            result = await orchestrator.approve_pending(
                message_id,
                manager_telegram_id=manager_id(request),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return result

    @app.post("/api/tasks/{task_id}/complete")
    async def complete_task(request: Request, task_id: int):
        try:
            await crm.complete_task(task_id, manager_id(request))
            return {"ok": True, "message": "Задача выполнена"}
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(request: Request, task_id: int):
        try:
            await crm.cancel_task(task_id, manager_id(request))
            return {"ok": True, "message": "Задача отменена"}
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/leads/{lead_id}/reopen")
    async def reopen_lead(request: Request, lead_id: int):
        try:
            lead = await crm.reopen_not_lead(lead_id, manager_id(request))
            return {
                "ok": True,
                "status": lead.status.value,
                "message": "Лид возвращён в работу",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/leads/{lead_id}/deal")
    async def create_or_update_deal(request: Request, lead_id: int):
        payload = await _json_or_form(request)
        try:
            amount = _decimal_or_none(payload.get("amount"))
            quantity = _int_or_none(payload.get("quantity"))
            deal = await crm.upsert_deal(
                lead_id,
                manager_id(request),
                product_name=str(payload.get("product_name") or ""),
                quantity=quantity,
                amount=amount,
            )
            return {"ok": True, "deal_id": deal.id, "message": "Сделка сохранена"}
        except (LeadWorkflowError, InvalidOperation, ValueError) as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/deals/{deal_id}/win")
    async def win_deal(request: Request, deal_id: int):
        payload = await _json_or_form(request)
        try:
            amount = _decimal_or_none(payload.get("amount"))
            if amount is None or amount < 0:
                raise ValueError("Укажите сумму продажи")
            quantity = _int_or_none(payload.get("quantity")) or 1
            deal = await workflow.win_deal(
                deal_id,
                manager_id(request),
                product_name=str(payload.get("product_name") or "Продажа"),
                product_id=_int_or_none(payload.get("product_id")),
                amount=amount,
                quantity=quantity,
                sale_currency=str(payload.get("currency") or "UZS"),
            )
            return {"ok": True, "status": deal.status.value, "message": "Продажа зафиксирована"}
        except (LeadWorkflowError, InvalidOperation, ValueError) as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/deals/{deal_id}/lose")
    async def lose_deal(request: Request, deal_id: int):
        payload = await _json_or_form(request)
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            raise HTTPException(
                status_code=400, detail="Укажите причину, почему сделка не состоялась"
            )
        try:
            deal = await workflow.lose_deal(deal_id, manager_id(request), reason=reason)
            return {
                "ok": True,
                "status": deal.status.value,
                "message": "Причина проигрыша сохранена",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/competitors/import")
    async def import_competitors_csv(request: Request, filename: str = "competitors.csv"):
        try:
            result = await competitor_import_service.import_file(filename, await request.body())
            return {
                "ok": True,
                "total_rows": result.total_rows,
                "created": result.created,
                "updated": result.updated,
                "skipped": result.skipped,
                "message": (
                    f"Импорт конкурентов: {result.created} новых на паузе, "
                    f"{result.updated} уже были в базе, {result.skipped} пропущено."
                ),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/competitors")
    async def add_competitor(request: Request):
        payload = await _json_or_form(request)
        try:
            competitor = await crm.add_competitor(
                str(payload.get("handle") or ""),
                display_name=str(payload.get("display_name") or ""),
                category=str(payload.get("category") or "DIRECT"),
                tier=str(payload.get("tier") or "A"),
                notes=str(payload.get("notes") or ""),
                vertical=str(payload.get("vertical") or "FURNITURE"),
            )
            return {
                "ok": True,
                "competitor_id": competitor.id,
                "message": f"@{competitor.normalized_handle} добавлен в мониторинг",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/market-catalog/sync")
    async def sync_market_catalog():
        result = await market_service.sync_catalog()
        return {
            "ok": True,
            "created_competitors": result["created_competitors"],
            "created_candidates": result["created_candidates"],
            "promoted_candidates": result["promoted_candidates"],
            "message": "Карта рынка синхронизирована. Новые конкуренты добавлены на паузе и не расходуют API.",
        }

    @app.post("/api/market-candidates/{candidate_id}/promote")
    async def promote_market_candidate(request: Request, candidate_id: int):
        payload = await _json_or_form(request)
        handle = str(payload.get("handle") or "").strip()
        active = str(payload.get("active") or "false").lower() in {"1", "true", "yes", "on"}
        try:
            competitor = await market_service.promote_candidate(
                candidate_id,
                handle=handle,
                active=active,
            )
            return {
                "ok": True,
                "competitor_id": competitor.id,
                "message": (
                    f"@{competitor.normalized_handle} добавлен в радар на "
                    f"{'активный мониторинг' if competitor.active else 'паузу'}. "
                    f"Открыть: /competitors/{competitor.id}"
                ),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discovery/import")
    async def import_discovery_file(request: Request, filename: str = "import.csv"):
        try:
            result = await discovery_service.import_file(filename, await request.body())
            return {
                "ok": True,
                **result.__dict__,
                "message": (
                    f"Импортировано: {result.created} новых, {result.updated} изменённых, "
                    f"{result.unchanged} без изменений. Дубликаты не создавались."
                ),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discovery/candidates/{candidate_id}/status")
    async def update_discovery_candidate(request: Request, candidate_id: int):
        payload = await _json_or_form(request)
        try:
            candidate = await discovery_service.set_status(
                candidate_id, str(payload.get("status") or "")
            )
            return {
                "ok": True,
                "status": candidate.status,
                "message": "Статус кандидата обновлён",
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/discovery/diffs/{diff_id}/acknowledge")
    async def acknowledge_discovery_diff(diff_id: int):
        try:
            await discovery_service.acknowledge_diff(diff_id)
            return {"ok": True, "message": "Изменение просмотрено"}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/catalog/import")
    async def import_catalog(request: Request):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="Выберите CSV-файл")
        try:
            result = await product_catalog_service.import_csv(
                filename=str(getattr(upload, "filename", "") or ""),
                content=await upload.read(),
                manager_id=manager_id(request),
                apply=str(form.get("apply") or "").lower() in {"1", "true", "yes"},
            )
            return {"ok": True, **result}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/catalog/{product_id}")
    async def update_catalog_product(request: Request, product_id: int):
        payload = await _json_or_form(request)
        active = None
        if "active" in payload:
            active = str(payload.get("active")).lower() in {"1", "true", "yes", "on"}
        try:
            product = await product_catalog_service.update_verified_fields(
                product_id,
                manager_id=manager_id(request),
                category=str(payload["category"]) if "category" in payload else None,
                price=payload.get("price") if "price" in payload else None,
                currency=str(payload["currency"]) if "currency" in payload else None,
                stock=payload.get("stock") if "stock" in payload else None,
                cogs=payload.get("cogs") if "cogs" in payload else None,
                active=active,
            )
            return {
                "ok": True,
                "product_id": product.id,
                "message": "Подтверждённые данные товара сохранены",
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/competitors/bulk-active")
    async def bulk_competitors_active(request: Request):
        payload = await _json_or_form(request)
        raw_ids = payload.get("competitor_ids") or payload.get("ids") or []
        if isinstance(raw_ids, str):
            raw_ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
        try:
            competitor_ids = [int(item) for item in raw_ids]
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail="Нужен список competitor_ids"
            ) from exc
        if "active" not in payload:
            raise HTTPException(status_code=400, detail="Укажите active=true или false")
        active = str(payload.get("active")).lower() in {"1", "true", "yes", "on"}
        try:
            changed = await crm.bulk_set_competitors_active(
                competitor_ids, active=active
            )
            action_label = "Включён мониторинг" if active else "Поставлено на паузу"
            return {
                "ok": True,
                "changed": changed,
                "active": active,
                "message": f"{action_label}: {changed}",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/competitors/{competitor_id}/settings")
    async def update_competitor(request: Request, competitor_id: int):
        payload = await _json_or_form(request)
        active = None
        if "active" in payload:
            active = str(payload.get("active")).lower() in {"1", "true", "yes", "on"}
        try:
            competitor = await crm.update_competitor(
                competitor_id,
                active=active,
                tier=str(payload.get("tier")) if payload.get("tier") else None,
                category=str(payload.get("category")) if payload.get("category") else None,
                vertical=str(payload.get("vertical")) if payload.get("vertical") else None,
                notification_policy=(
                    str(payload.get("notification_policy"))
                    if payload.get("notification_policy")
                    else None
                ),
            )
            return {
                "ok": True,
                "active": competitor.active,
                "tier": competitor.tier,
                "vertical": competitor.vertical.value,
                "notification_policy": (
                    competitor.notification_policy.value
                    if competitor.notification_policy
                    else "INHERIT"
                ),
                "message": "Настройки конкурента сохранены",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.get("/api/radar/feed")
    async def radar_feed_api(limit: int = 8):
        safe_limit = max(1, min(limit, 20))
        payload = await queries.radar_feed(limit=safe_limit)
        snapshot = controller.snapshot()
        payload["cycle_running"] = snapshot.cycle_running
        payload["last_error"] = snapshot.last_error
        payload["scan_progress"] = snapshot.progress.to_dict()
        payload["last_stats"] = (
            {
                "competitors_checked": snapshot.last_stats.competitors_checked,
                "reels_found": snapshot.last_stats.reels_found,
                "comments_created": snapshot.last_stats.comments_created,
                "leads_created": snapshot.last_stats.leads_created,
                "errors": snapshot.last_stats.errors,
                "budget_stops": snapshot.last_stats.budget_stops,
                "hot_notifications": snapshot.last_stats.hot_notifications,
            }
            if snapshot.last_stats is not None
            else None
        )
        payload["cycles_completed"] = snapshot.cycles_completed
        if analysis_pipeline is not None:
            payload["analysis_queue"] = analysis_pipeline.pending_count
            payload["analysis_in_flight"] = analysis_pipeline.in_flight_count
            payload["ai_analysis_max_concurrency"] = ops_control.snapshot().ai_analysis_max_concurrency
        else:
            payload["analysis_queue"] = 0
            payload["analysis_in_flight"] = 0
        return payload

    @app.get("/api/scan/progress")
    async def scan_progress_api():
        """Лёгкий endpoint для live-прогресса проверки на любой странице."""
        snapshot = controller.snapshot()
        payload = {
            "ok": True,
            "cycle_running": snapshot.cycle_running,
            "cycle_trigger": snapshot.cycle_trigger,
            "last_error": snapshot.last_error,
            "progress": snapshot.progress.to_dict(),
            "cycles_completed": snapshot.cycles_completed,
            "last_stats": (
                {
                    "competitors_checked": snapshot.last_stats.competitors_checked,
                    "reels_found": snapshot.last_stats.reels_found,
                    "comments_created": snapshot.last_stats.comments_created,
                    "leads_created": snapshot.last_stats.leads_created,
                    "errors": snapshot.last_stats.errors,
                    "budget_stops": snapshot.last_stats.budget_stops,
                    "hot_notifications": snapshot.last_stats.hot_notifications,
                }
                if snapshot.last_stats is not None
                else None
            ),
        }
        if analysis_pipeline is not None:
            payload["analysis_queue"] = analysis_pipeline.pending_count
            payload["analysis_in_flight"] = analysis_pipeline.in_flight_count
        else:
            payload["analysis_queue"] = 0
            payload["analysis_in_flight"] = 0
        feed = await queries.gpt_queue_counts()
        payload["ai_pending"] = int(feed.get("ai_pending") or 0)
        payload["analyzing"] = int(feed.get("analyzing") or 0)
        payload["gpt_queue_total"] = payload["ai_pending"] + payload["analyzing"]
        return payload

    @app.get("/health")
    async def health():
        snapshot = controller.snapshot()
        payload = {
            "safe_mode": not radar_spend_allowed(),
            "ok": True,
            "cycle_running": snapshot.cycle_running,
            "cycles_completed": snapshot.cycles_completed,
            "last_error": snapshot.last_error,
            "scan_progress": snapshot.progress.to_dict(),
            "radar_live_armed": ops_control.radar_live_armed(),
            "openai_live_armed": ops_control.openai_live_armed(),
            "master_live_ready": master_live_ready(),
        }
        if analysis_pipeline is not None:
            payload["analysis_queue"] = analysis_pipeline.pending_count
            payload["analysis_in_flight"] = analysis_pipeline.in_flight_count
            payload["ai_analysis_max_concurrency"] = ops_control.snapshot().ai_analysis_max_concurrency
        return payload

    @app.get("/ready")
    async def ready():
        from sqlalchemy import func, select

        from app.db.models import Competitor

        state = await inspect_offline_readiness(settings)
        payload = {
            "ok": state.ready,
            "database_healthy": state.database_healthy,
            "migration_at_head": state.migration_at_head,
            "migration_drift_free": state.migration_drift_free,
            "backup_present": state.backup_present,
            "uncertain_reservations": state.uncertain_reservations,
            "web_enabled": settings.web_enabled,
            "radar_live_armed": ops_control.radar_live_armed(),
            "openai_live_armed": ops_control.openai_live_armed(),
            "blocks": list(state.offline_blocks),
        }
        if analysis_pipeline is not None:
            payload["analysis_queue"] = analysis_pipeline.pending_count
            payload["analysis_in_flight"] = analysis_pipeline.in_flight_count
        async with workflow.session_factory() as session:
            payload["active_competitors"] = int(
                await session.scalar(select(func.count(Competitor.id)).where(Competitor.active))
                or 0
            )
            payload["competitors_total"] = int(
                await session.scalar(select(func.count(Competitor.id))) or 0
            )
        status_code = 200 if state.ready else 503
        return JSONResponse(payload, status_code=status_code)

    return app


async def _json_or_form(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    form = await request.form()
    return dict(form)


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value).replace(" ", "").replace(",", "."))


def _int_or_none(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Некорректное числовое значение") from exc


def _required_positive_int(value: object, *, field: str) -> int:
    if value in (None, ""):
        raise HTTPException(status_code=400, detail=f"{field} required")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Некорректный {field}") from exc
    if parsed <= 0:
        raise HTTPException(status_code=400, detail=f"{field} required")
    return parsed


def _optional_int(value: object, *, field: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Некорректный {field}") from exc


def _human_workflow_error(exc: Exception) -> str:
    text = str(exc)
    replacements = {
        "Lead not found": "Лид не найден",
        "Deal not found": "Сделка не найдена",
        "Deal is already closed": "Сделка уже закрыта",
    }
    return replacements.get(text, text)
