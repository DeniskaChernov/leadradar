from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings
from app.db.models import LeadStatus, NotificationPolicy
from app.services.ai_service import HybridLeadAnalyzer, RuleBasedLeadAnalyzer
from app.services.audience_facet_service import AudienceFacetQuery
from app.services.audience_service import AudienceEngine
from app.services.crm_service import CRMService
from app.services.discovery_service import DiscoveryService
from app.services.export_recipe_service import ExportRecipeService
from app.services.lead_intelligence_challenge import LeadIntelligenceChallenge
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowError, LeadWorkflowService
from app.services.market_intelligence_service import MarketIntelligenceService
from app.services.meta_audience_service import MetaAudiencePlanningService
from app.services.monitor_controller import MonitorController
from app.services.notification_readiness_service import NotificationReadinessService
from app.services.pricing_config_service import PricingConfigService
from app.services.product_catalog_service import (
    ALLOWED_PRODUCT_CATEGORIES,
    ProductCatalogService,
)
from app.services.significant_change_service import SignificantChangeDetector
from app.services.usage_service import ExternalUsageService
from app.web.auth import TelegramAuthError, TelegramWebAuth, WebRole, required_role
from app.web.labels import (
    AI_SOURCE_LABELS,
    BUYER_ROLE_ICONS,
    BUYER_ROLE_LABELS,
    CHANGE_TYPE_LABELS,
    CHANNEL_LABELS,
    COMMERCIAL_STAGE_LABELS,
    COMPETITOR_CATEGORY_LABELS,
    COVERAGE_LABELS,
    DEAL_STATUS_LABELS,
    EVENT_LABELS,
    EXPORT_ELIGIBILITY_LABELS,
    FUNNEL_STAGE_LABELS,
    INTENT_LABELS,
    LEAD_STATUS_LABELS,
    PRODUCT_LABELS,
    PURCHASE_HORIZON_LABELS,
    QUALIFICATION_FIELD_LABELS,
    RUN_STATUS_LABELS,
    TRIGGER_LABELS,
    URGENCY_LABELS,
    label,
)
from app.web.queries import WebQueryService


def build_web_app(
    settings: Settings,
    queries: WebQueryService,
    workflow: LeadWorkflowService,
    controller: MonitorController,
    usage_service: ExternalUsageService | None = None,
    lead_service: LeadService | None = None,
    crm: CRMService | None = None,
    notification_worker_active: bool = False,
) -> FastAPI:
    app = FastAPI(title="Lead Radar", docs_url="/api/docs", redoc_url=None)
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
    auth = TelegramWebAuth(settings)
    usage_service = usage_service or ExternalUsageService(workflow.session_factory)
    crm = crm or CRMService(workflow.session_factory)
    # The Mini App button "Разобрать сохранённые сигналы" is intentionally local-only.
    # Even if production OpenAI is unlocked elsewhere, this service has no network analyzer, so
    # an ambiguous signal becomes AI_PENDING instead of silently spending tokens.
    market_service = MarketIntelligenceService(workflow.session_factory)
    meta_audience_service = MetaAudiencePlanningService(workflow.session_factory)
    discovery_service = DiscoveryService(workflow.session_factory)
    product_catalog_service = ProductCatalogService(workflow.session_factory)
    local_audience_engine = AudienceEngine(workflow.session_factory, settings.hot_lead_threshold)
    local_lead_service = LeadService(
        workflow.session_factory,
        HybridLeadAnalyzer(RuleBasedLeadAnalyzer(), None, mode="hybrid"),
        settings.hot_lead_threshold,
        audience_engine=local_audience_engine,
        change_detector=SignificantChangeDetector(
            workflow.session_factory, hot_threshold=settings.hot_lead_threshold
        ),
    )
    delivery_allowed_by_config = bool(settings.telegram_bot_token) and (
        settings.instagram_provider not in {"mock", "replay"}
    )
    notification_readiness_service = NotificationReadinessService(
        workflow.session_factory,
        workflow,
        admin_chat_ids=settings.telegram_admin_chat_ids,
        default_policy=NotificationPolicy(settings.notification_policy),
        hot_threshold=settings.hot_lead_threshold,
        token_configured=bool(settings.telegram_bot_token),
        delivery_allowed_by_config=delivery_allowed_by_config,
        worker_active=notification_worker_active,
    )
    pricing_service = PricingConfigService(workflow.session_factory)
    intelligence_challenge = LeadIntelligenceChallenge()

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
        channel_label=lambda value: label(CHANNEL_LABELS, value, "Не указан"),
        qualification_field_label=lambda value: label(
            QUALIFICATION_FIELD_LABELS, value, str(value)
        ),
        buyer_role_label=lambda value: label(BUYER_ROLE_LABELS, value, "Не определено"),
        buyer_role_icon=lambda value: BUYER_ROLE_ICONS.get(
            str(value) if value else "UNKNOWN", "❓"
        ),
        money=lambda value: f"{float(value or 0):,.0f}".replace(",", " "),
    )

    def local_manager_id() -> int:
        if settings.web_manager_id:
            return settings.web_manager_id
        if settings.telegram_admin_chat_ids:
            return settings.telegram_admin_chat_ids[0]
        return 1

    @app.middleware("http")
    async def protect_mini_app(request: Request, call_next):
        public_paths = {"/auth", "/api/auth/telegram", "/health"}
        if not settings.web_auth_enabled:
            request.state.manager_id = local_manager_id()
            request.state.web_role = WebRole.ADMIN
            request.state.csrf_token = ""
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
            "safe_mode": (
                settings.instagram_provider in {"mock", "replay"}
                or not settings.instagram_live_enabled
            ),
            "search_paused": not settings.lead_search_enabled,
            "telegram_manager_count": len(settings.telegram_admin_chat_ids),
            "selected_vertical": selected_vertical,
            **kwargs,
        }

    def manager_id(request: Request) -> int:
        return int(getattr(request.state, "manager_id", local_manager_id()))

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
            ),
        )

    @app.get("/leads", response_class=HTMLResponse)
    async def leads(request: Request, q: str = "", status: str = "", view: str = "board"):
        rows = await queries.leads(q=q, status=status)
        return templates.TemplateResponse(
            request=request,
            name="leads.html",
            context=base_context(
                request,
                rows=rows,
                q=q,
                status_filter=status,
                view=view,
                board_statuses=[
                    "NEW",
                    "TAKEN",
                    "CONTACTED",
                    "QUALIFIED",
                    "OFFER_SENT",
                    "NEGOTIATION",
                ],
            ),
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

    @app.get("/audiences", response_class=HTMLResponse)
    async def audiences(request: Request, vertical: str = "FURNITURE"):
        rows = await queries.audiences(vertical=vertical)
        return templates.TemplateResponse(
            request=request,
            name="audiences.html",
            context=base_context(request, rows=rows),
        )

    @app.get("/audiences/{slug}", response_class=HTMLResponse)
    async def audience_detail(request: Request, slug: str):
        facets = AudienceFacetQuery.from_mapping(request.query_params)
        data = await queries.audience_detail(slug, facets=facets)
        if data is None:
            raise HTTPException(status_code=404, detail="Аудитория не найдена")
        meta_readiness = await meta_audience_service.readiness(slug)
        return templates.TemplateResponse(
            request=request,
            name="audience_detail.html",
            context=base_context(request, meta_readiness=meta_readiness, **data),
        )

    @app.get("/competitors", response_class=HTMLResponse)
    async def competitors(request: Request):
        rows = await queries.competitors()
        overview = await queries.market_overview()
        intelligence_overview = await queries.competitor_intelligence_overview()
        overlaps = await queries.competitor_overlap_network()
        return templates.TemplateResponse(
            request=request,
            name="competitors.html",
            context=base_context(
                request,
                rows=rows,
                market_overview=overview,
                intelligence_overview=intelligence_overview,
                overlaps=overlaps,
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
            live_enabled=settings.instagram_live_enabled,
        )
        replay_scenario = getattr(getattr(controller.monitor, "provider", None), "scenario", None)
        replay_status = replay_scenario.status() if replay_scenario is not None else None
        notification_readiness = await notification_readiness_service.preview(limit=10)
        ai_safety = await queries.ai_safety_diagnostics()
        intelligence_quality = intelligence_challenge.evaluate(
            hot_threshold=settings.hot_lead_threshold
        )
        pricing_configs = await pricing_service.list_active()
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
        integrations = {
            "Telegram": {
                "configured": bool(settings.telegram_bot_token),
                "enabled": production_notifications,
                "detail": (
                    "Production-уведомления включены"
                    if production_notifications
                    else "Replay/mock не отправляет production-уведомления"
                ),
            },
            "Локальный анализ": {
                "configured": True,
                "enabled": True,
                "detail": "Работает без токенов",
            },
            "OpenAI": {
                "configured": bool(settings.openai_api_key),
                "enabled": settings.openai_live_enabled,
                "detail": f"{usage.get('openai', 0)}/{settings.openai_daily_request_limit} запросов сегодня",
            },
            "ScrapeCreators / Bright Data": {
                "configured": bool(settings.scrapecreators_api_key or settings.brightdata_api_key),
                "enabled": settings.instagram_live_enabled,
                "detail": f"{usage.get('instagram', 0)}/{settings.instagram_daily_request_limit} операций сегодня",
            },
            "AI Agent / MCP": {
                "configured": False,
                "enabled": False,
                "detail": "NOT_CONNECTED · демонстрационные ответы отключены",
            },
            "Meta / Google": {
                "configured": False,
                "enabled": False,
                "detail": "NOT_CONNECTED · статические прототипы не являются live API",
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
                ai_safety=ai_safety,
                intelligence_quality=intelligence_quality,
                pricing_configs=pricing_configs,
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
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "ok": True,
            "pricing_config_id": config.id,
            "message": "Новая версия цены сохранена; предыдущая осталась в истории.",
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

    async def _scan_preview_payload() -> dict:
        usage = await queries.usage_today()
        instagram_remaining = max(
            0, settings.instagram_daily_request_limit - usage.get("instagram", 0)
        )
        plan = await queries.scan_plan(
            max_units_per_scan=settings.instagram_max_units_per_scan,
            daily_remaining=instagram_remaining,
            live_enabled=settings.instagram_live_enabled,
        )
        is_live = settings.instagram_provider not in {"mock", "replay"}
        return {
            "ok": True,
            "search_enabled": settings.lead_search_enabled,
            "is_live": is_live,
            "provider": settings.instagram_provider,
            "live_enabled": settings.instagram_live_enabled,
            "requires_confirmation": is_live,
            "plan": plan,
        }

    @app.get("/api/scan/preview")
    async def scan_preview(request: Request):
        return await _scan_preview_payload()

    @app.post("/api/scan")
    async def scan_now(request: Request):
        if not settings.lead_search_enabled:
            raise HTTPException(
                status_code=409,
                detail="Поиск лидов временно приостановлен. Внешние токены не расходуются.",
            )
        payload = await _json_or_form(request)
        is_live = settings.instagram_provider not in {"mock", "replay"}
        if is_live and not settings.instagram_live_enabled:
            raise HTTPException(
                status_code=409,
                detail="Реальные Instagram-запросы выключены, поэтому токены не будут потрачены. Включайте их только перед контрольным тестом.",
            )
        if is_live and payload.get("confirm_live") is not True:
            raise HTTPException(
                status_code=428,
                detail="Live-проверка требует отдельного подтверждения расхода.",
            )
        started = controller.start_cycle("web")
        return JSONResponse(
            {
                "ok": started,
                "message": "Проверка запущена" if started else "Проверка уже выполняется",
            }
        )

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
                f"Локально разобрано сигналов: {len(results)}. "
                f"Неоднозначных оставлено на AI: {pending}. OpenAI не вызывался."
            ),
        }

    @app.post("/api/leads/{lead_id}/take")
    async def take_lead(request: Request, lead_id: int):
        try:
            lead = await workflow.assign_manager(lead_id, manager_id(request))
            return {"ok": True, "status": lead.status.value, "message": "Лид взят в работу"}
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/leads/{lead_id}/not-lead")
    async def not_lead(request: Request, lead_id: int):
        try:
            lead = await workflow.mark_not_lead(lead_id, manager_id(request))
            return {"ok": True, "status": lead.status.value, "message": "Сигнал помечен как не лид"}
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=409, detail=_human_workflow_error(exc)) from exc

    @app.post("/api/leads/{lead_id}/stage")
    async def move_lead(request: Request, lead_id: int):
        payload = await _json_or_form(request)
        try:
            target = LeadStatus(str(payload.get("status") or "").upper())
            lead = await crm.move_lead(lead_id, manager_id(request), target)
            return {"ok": True, "status": lead.status.value, "message": "Стадия обновлена"}
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
            due_at = datetime.fromisoformat(str(payload.get("due_at") or ""))
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Укажите дату и время следующего контакта"
            ) from exc
        lead_id_raw = payload.get("lead_id")
        lead_id = int(lead_id_raw) if lead_id_raw not in (None, "") else None
        try:
            await crm.schedule_next_contact(
                contact_id,
                manager_id(request),
                due_at,
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
        raise HTTPException(
            status_code=503,
            detail=(
                "AI Agent пока не подключён. Старый демонстрационный ответ отключён, "
                "потому что он не был основан на данных Lead Radar."
            ),
        )

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
                "message": f"@{competitor.normalized_handle} добавлен в радар на {'активный мониторинг' if competitor.active else 'паузу'}",
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
                "notification_policy": (
                    competitor.notification_policy.value
                    if competitor.notification_policy
                    else "INHERIT"
                ),
                "message": "Настройки конкурента сохранены",
            }
        except LeadWorkflowError as exc:
            raise HTTPException(status_code=400, detail=_human_workflow_error(exc)) from exc

    @app.get("/health")
    async def health():
        snapshot = controller.snapshot()
        return {
            "ok": True,
            "cycle_running": snapshot.cycle_running,
            "cycles_completed": snapshot.cycles_completed,
            "last_error": snapshot.last_error,
            "safe_mode": (
                settings.instagram_provider in {"mock", "replay"}
                or not settings.instagram_live_enabled
            ),
        }

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
    return int(value)


def _human_workflow_error(exc: Exception) -> str:
    text = str(exc)
    replacements = {
        "Lead not found": "Лид не найден",
        "Deal not found": "Сделка не найдена",
        "Deal is already closed": "Сделка уже закрыта",
    }
    return replacements.get(text, text)
