"""HOT outreach: черновик Instagram DM + движение по воронке после отправки."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import case, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.db.models import (
    Comment,
    Competitor,
    Contact,
    ContactEventType,
    ExternalBudgetReservation,
    Lead,
    LeadStatus,
    Post,
    ReservationStatus,
    Vertical,
)
from app.db.repositories.events import ContactEventRepository
from app.services.assortment_policy import assortment_eligible, assortment_eligible_clause
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowError, LeadWorkflowService
from app.services.product_catalog_service import ProductCatalogService
from app.services.signal_recency import fresh_signal_clause
from app.services.usage_service import ExternalBudgetExceeded, ExternalUsageService

logger = logging.getLogger(__name__)

HOT_OUTREACH_KEY = "hot_outreach"
OPEN_HOT_STATUSES = {
    LeadStatus.ANALYZING,
    LeadStatus.AI_PENDING,
    LeadStatus.NEW,
    LeadStatus.TAKEN,
    LeadStatus.CONTACTED,
    LeadStatus.QUALIFIED,
}

# Контакт уже в работе/писали — чтобы не слать повторно вслепую.
PRIOR_OUTREACH_STATUSES = {
    LeadStatus.CONTACTED,
    LeadStatus.QUALIFIED,
    LeadStatus.OFFER_SENT,
    LeadStatus.NEGOTIATION,
    LeadStatus.WON,
}


class OutreachComposer(Protocol):
    async def compose(self, context: dict[str, Any]) -> str: ...


class StaticOutreachComposer:
    """Только для тестов: фиксированный текст без сети."""

    def __init__(
        self, text: str = "Здравствуйте! Могу предложить подходящий вариант из каталога."
    ) -> None:
        self.text = text

    async def compose(self, context: dict[str, Any]) -> str:
        return self.text.strip()


class OpenAIOutreachComposer:
    """Короткий Instagram DM на фактах лида и каталога."""

    def __init__(self, api_key: str, model: str, client: Any | None = None) -> None:
        self.model = model
        if client is not None:
            self.client = client
        else:
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(api_key=api_key, max_retries=0, timeout=60.0)

    async def compose(self, context: dict[str, Any]) -> str:
        instructions = (
            "Ты помощник менеджера Lead Radar. Напиши одно короткое личное сообщение "
            "для Instagram Direct по фактам из JSON. Только текст сообщения, без кавычек, "
            "без markdown, без пояснений. 2–5 предложений. Язык = язык комментария клиента "
            "(русский / узбекский / смешанный). Не выдумывай цены, наличие и свойства, "
            "которых нет во входных данных. Если товара нет — мягко уточни потребность. "
            "Не проси телефон/email. Не упоминай, что ты ИИ."
        )
        options = {}
        if self.model.startswith("gpt-5"):
            options["reasoning"] = {"effort": "low"}
        response = await self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=json.dumps(context, ensure_ascii=False, default=str),
            # This cap includes reasoning tokens, which could consume the old 500
            # token budget before the model produced any customer-facing text.
            max_output_tokens=2000,
            store=False,
            prompt_cache_key="lead-radar-hot-outreach-v1",
            **options,
        )
        if getattr(response, "status", None) == "incomplete":
            raise LeadWorkflowError(
                "OpenAI не завершил текст предложения. Повторите подготовку текста."
            )
        text = (getattr(response, "output_text", None) or "").strip()
        if not text:
            raise LeadWorkflowError("OpenAI вернул пустой текст предложения")
        return text


@dataclass(frozen=True, slots=True)
class HotOutreachDraft:
    message: str
    prepared_at: str
    prepared_by: int | None
    recommendation_title: str | None
    product_id: int | None
    product_sku: str | None
    sent_at: str | None


class HotOutreachService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
        workflow: LeadWorkflowService,
        crm: CRMService,
        catalog: ProductCatalogService,
        usage: ExternalUsageService | None = None,
        composer: OutreachComposer | None = None,
        openai_daily_limit: int = 200,
        signal_max_age_days: int = 30,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold
        self.workflow = workflow
        self.crm = crm
        self.catalog = catalog
        self.usage = usage
        self.composer = composer
        self.openai_daily_limit = openai_daily_limit
        self.signal_max_age_days = max(0, signal_max_age_days)

    @staticmethod
    def _sent_clause(model):
        return (
            func.coalesce(model.analysis_details[HOT_OUTREACH_KEY]["sent_at"].as_string(), "") != ""
        )

    def _queue_query(self, vertical: str | None):
        prior = aliased(Lead)
        already_contacted = (
            select(prior.id)
            .where(
                prior.contact_id == Lead.contact_id,
                prior.id != Lead.id,
                or_(prior.status.in_(PRIOR_OUTREACH_STATUSES), self._sent_clause(prior)),
            )
            .correlate(Lead)
            .exists()
        )
        sent = self._sent_clause(Lead)
        stmt = (
            select(
                Lead,
                Contact,
                Comment,
                Competitor,
                Post,
                already_contacted.label("already_contacted"),
            )
            .join(Contact, Contact.id == Lead.contact_id)
            .join(Comment, Comment.id == Lead.comment_id)
            .join(Competitor, Competitor.id == Lead.competitor_id)
            .join(Post, Post.id == Comment.post_id)
            .where(
                Lead.lead_score >= self.hot_threshold,
                assortment_eligible_clause(Lead),
                Lead.status.in_(OPEN_HOT_STATUSES),
                fresh_signal_clause(max_age_days=self.signal_max_age_days),
            )
        )
        vertical_enum = self._parse_vertical(vertical)
        if vertical_enum is not None:
            stmt = stmt.where(Lead.vertical == vertical_enum)
        return stmt, already_contacted, sent

    async def queue_count(self, *, vertical: str | None = None) -> int:
        stmt, _, _ = self._queue_query(vertical)
        async with self.session_factory() as session:
            return int(await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)

    async def contact_target(self, contact_id: int) -> dict[str, Any] | None:
        """Choose this contact's first actionable lead using the complete HOT queue."""
        stmt, already_contacted, sent = self._queue_query(None)
        stmt = (
            stmt.with_only_columns(Lead.id, Lead.vertical)
            .where(Lead.contact_id == contact_id)
            .order_by(*self._queue_ordering(already_contacted, sent))
            .limit(1)
        )
        async with self.session_factory() as session:
            row = (await session.execute(stmt)).first()
        return {"lead_id": row.id, "vertical": row.vertical.value} if row else None

    async def queue(
        self,
        *,
        vertical: str | None = None,
        limit: int = 80,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt, already_contacted, sent = self._queue_query(vertical)
        stmt = (
            stmt.order_by(*self._queue_ordering(already_contacted, sent))
            .limit(max(1, min(limit, 200)))
            .offset(max(0, offset))
        )
        async with self.session_factory() as session:
            rows = (await session.execute(stmt)).all()
        return [
            self._queue_item(
                lead,
                contact,
                comment,
                competitor,
                post,
                already_contacted=bool(prior_contact),
            )
            for lead, contact, comment, competitor, post, prior_contact in rows
        ]

    @staticmethod
    def _queue_ordering(already_contacted, sent):
        return (
            case((already_contacted, 1), else_=0),
            case((sent, 1), else_=0),
            desc(Lead.lead_score),
            desc(Lead.created_at),
            desc(Lead.id),
        )

    async def queue_position(self, lead_id: int, *, vertical: str | None = None) -> int | None:
        """Locate a selected lead using the complete queue's filters and ordering."""
        stmt, already_contacted, sent = self._queue_query(vertical)
        ranked = stmt.with_only_columns(
            Lead.id.label("lead_id"),
            (
                func.row_number().over(order_by=self._queue_ordering(already_contacted, sent)) - 1
            ).label("position"),
        ).subquery()
        async with self.session_factory() as session:
            position = await session.scalar(
                select(ranked.c.position).where(ranked.c.lead_id == lead_id)
            )
        return int(position) if position is not None else None

    async def next_queue_lead_id(
        self,
        *,
        vertical: str | None = None,
        exclude_lead_id: int | None = None,
    ) -> int | None:
        """Следующий HOT после текущего — для непрерывного дневного цикла."""
        stmt, already_contacted, sent = self._queue_query(vertical)
        stmt = stmt.with_only_columns(Lead.id).where(~already_contacted, ~sent)
        if exclude_lead_id is not None:
            stmt = stmt.where(Lead.id != exclude_lead_id)
        stmt = stmt.order_by(desc(Lead.lead_score), desc(Lead.created_at), desc(Lead.id)).limit(1)
        async with self.session_factory() as session:
            return await session.scalar(stmt)

    async def detail(
        self,
        lead_id: int,
        *,
        vertical: str | None = None,
        include_saved_history: bool = False,
    ) -> dict[str, Any] | None:
        vertical_enum = self._parse_vertical(vertical)
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(Lead, Contact, Comment, Competitor, Post)
                    .join(Contact, Contact.id == Lead.contact_id)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .join(Competitor, Competitor.id == Lead.competitor_id)
                    .join(Post, Post.id == Comment.post_id)
                    .where(Lead.id == lead_id)
                )
            ).one_or_none()
            if row is None:
                return None
            lead, contact, comment, competitor, post = row
            if vertical_enum is not None and lead.vertical != vertical_enum:
                return None
            draft = self._read_draft(lead)
            if (lead.lead_score < self.hot_threshold or not assortment_eligible(lead.analysis_details)) and not (include_saved_history and draft):
                return None
            contact_history = await self._contact_outreach_summary(
                session, contact.id, exclude_lead_id=lead.id
            )
        recommendation = await self.catalog.recommend_for_lead(lead)
        writable = (
            lead.lead_score >= self.hot_threshold
            and assortment_eligible(lead.analysis_details)
            and lead.status in OPEN_HOT_STATUSES
            and not (draft and draft.sent_at)
        )
        product_context = (lead.analysis_details or {}).get("product_context")
        product_context = product_context if isinstance(product_context, dict) else {}
        product_categories = product_context.get("categories", [])
        product_categories = product_categories if isinstance(product_categories, list) else []
        return {
            "lead_id": lead.id,
            "status": lead.status.value,
            "score": lead.lead_score,
            "intent": lead.intent,
            "product_category": lead.product_category,
            "product_categories": list(dict.fromkeys(
                item for item in product_categories if isinstance(item, str) and item
            )) if lead.product_category == "MIXED_FURNITURE" else [],
            "ai_reason": lead.ai_reason,
            "language": lead.language,
            "vertical": lead.vertical.value,
            "username": contact.username,
            "display_name": contact.display_name,
            "profile_url": contact.profile_url,
            "contact_id": contact.id,
            "comment_text": comment.text,
            "competitor": competitor.normalized_handle,
            "post_url": post.url,
            "recommendation": {
                "title": recommendation.title,
                "description": recommendation.description,
                "product_id": recommendation.recommended_product_id,
                "product_sku": recommendation.recommended_sku,
            },
            "draft": asdict(draft) if draft is not None else None,
            "can_mark_sent": bool(writable and draft),
            "can_save_draft": bool(writable),
            "can_prepare": bool(writable and (self.composer is not None or draft)),
            "already_sent": draft is not None and draft.sent_at is not None,
            "contact_history": contact_history,
        }

    async def prepare(
        self,
        lead_id: int,
        manager_id: int,
        *,
        force: bool = False,
        allow_generation: bool = True,
    ) -> dict[str, Any]:
        async with self._claim(lead_id) as token:
            return await self._prepare_claimed(
                lead_id,
                manager_id,
                force=force,
                claim_token=token,
                allow_generation=allow_generation,
            )

    @asynccontextmanager
    async def _claim(self, lead_id: int):
        """Serialize all HOT writes, including manual edits during a slow AI call."""
        token = uuid4().hex
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            result = await session.execute(
                update(Lead)
                .where(
                    Lead.id == lead_id,
                    or_(
                        Lead.outreach_claim_token.is_(None),
                        Lead.outreach_claim_expires_at <= now,
                    ),
                )
                .values(
                    outreach_claim_token=token,
                    outreach_claim_expires_at=now + timedelta(seconds=180),
                    updated_at=Lead.updated_at,
                )
            )
            await session.commit()
            if result.rowcount != 1:
                raise LeadWorkflowError(
                    "Карточка уже обрабатывается: черновик уже готовится либо сохраняется правка. "
                    "Обновите карточку."
                )
        try:
            yield token
        finally:
            async with self.session_factory() as session:
                await session.execute(
                    update(Lead)
                    .where(Lead.id == lead_id, Lead.outreach_claim_token == token)
                    .values(
                        outreach_claim_token=None,
                        outreach_claim_expires_at=None,
                        updated_at=Lead.updated_at,
                    )
                )
                await session.commit()

    async def _prepare_claimed(
        self,
        lead_id: int,
        manager_id: int,
        *,
        force: bool,
        claim_token: str,
        allow_generation: bool,
    ) -> dict[str, Any]:
        lead = await self._get_lead(lead_id)
        self._assert_editable(lead, manager_id)
        cached = self._read_draft(lead)
        if cached and not force:
            detail = await self.detail(lead_id)
            if detail is None:
                raise LeadWorkflowError("HOT-лид не найден")
            return detail
        if not allow_generation or self.composer is None:
            raise LeadWorkflowError(
                "Подготовка текста недоступна: OpenAI выключен. Включите тумблер OpenAI в системе."
            )
        await self._ensure_taken(lead_id, manager_id)
        detail = await self.detail(lead_id)
        if detail is None:
            raise LeadWorkflowError("HOT-лид не найден")
        context = {
            "username": detail["username"],
            "comment_text": detail["comment_text"],
            "language": detail["language"],
            "intent": detail["intent"],
            "product_category": detail["product_category"],
            "product_categories": detail["product_categories"],
            "ai_reason": detail["ai_reason"],
            "score": detail["score"],
            "recommendation_title": detail["recommendation"]["title"],
            "recommendation_description": detail["recommendation"]["description"],
            "product_name": detail["recommendation"]["product_sku"]
            or detail["recommendation"]["title"],
            "product_sku": detail["recommendation"]["product_sku"],
            "competitor": detail["competitor"],
        }

        reservation_id = None
        if self.usage is not None:
            async with self.session_factory() as session:
                unresolved = await session.scalar(
                    select(ExternalBudgetReservation.id)
                    .where(
                        ExternalBudgetReservation.request_fingerprint.in_(
                            [f"hot-outreach:{lead_id}:False", f"hot-outreach:{lead_id}:True"]
                        ),
                        ExternalBudgetReservation.status.in_(
                            [
                                ReservationStatus.RESERVED,
                                ReservationStatus.EXPIRED,
                                ReservationStatus.UNCERTAIN,
                            ]
                        ),
                        or_(
                            ExternalBudgetReservation.call_started_at.is_not(None),
                            ExternalBudgetReservation.status == ReservationStatus.UNCERTAIN,
                        ),
                    )
                    .limit(1)
                )
            if unresolved is not None:
                raise LeadWorkflowError(
                    "Исход предыдущего AI-запроса неизвестен. Администратор должен сверить списание в системе."
                )
            try:
                reservation_id = await self.usage.reserve_budget(
                    "openai",
                    "hot_outreach_compose",
                    self.openai_daily_limit,
                    units=1,
                    estimated_cost=0.0,
                    request_fingerprint=f"hot-outreach:{lead_id}:{force}",
                    reservation_key=f"hot-outreach:{lead_id}:{claim_token}",
                    worker_id="hot-outreach",
                    provider="openai",
                )
            except ExternalBudgetExceeded as exc:
                raise LeadWorkflowError(str(exc)) from exc
            await self.usage.mark_call_started(reservation_id)

        try:
            message = (await self.composer.compose(context)).strip()
            if not message:
                raise LeadWorkflowError("Пустой текст предложения")
            if reservation_id is not None and self.usage is not None:
                await self.usage.finalize_reservation(
                    reservation_id,
                    units=1,
                    success=True,
                    details={"operation": "hot_outreach_compose"},
                    lead_id=lead_id,
                    unit_source="ESTIMATED",
                )
        except LeadWorkflowError:
            if reservation_id is not None and self.usage is not None:
                await self.usage.finalize_reservation(
                    reservation_id,
                    units=1,
                    success=False,
                    details={"operation": "hot_outreach_compose_failed"},
                    lead_id=lead_id,
                    unit_source="ESTIMATED",
                )
            raise
        except Exception as exc:
            logger.warning(
                "hot_outreach_compose_failed lead_id=%s error_type=%s", lead_id, type(exc).__name__
            )
            if reservation_id is not None and self.usage is not None:
                await self.usage.mark_reservation_uncertain(
                    reservation_id,
                    reason="hot_outreach_failed_after_call_started",
                    details={
                        "operation": "hot_outreach_compose_failed",
                        "error_type": type(exc).__name__,
                    },
                )
            raise LeadWorkflowError("Не удалось подготовить текст через OpenAI") from exc

        prepared_at = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
            await self._lock_lead_write(session, lead_id)
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise LeadWorkflowError("Лид не найден")
            details = dict(lead.analysis_details or {})
            details[HOT_OUTREACH_KEY] = {
                "message": message,
                "prepared_at": prepared_at,
                "prepared_by": manager_id,
                "recommendation_title": detail["recommendation"]["title"],
                "product_id": detail["recommendation"]["product_id"],
                "product_sku": detail["recommendation"]["product_sku"],
                "sent_at": None,
            }
            result = await session.execute(
                update(Lead)
                .where(*self._editable_write_conditions(lead_id, manager_id, claim_token))
                .values(analysis_details=details, updated_at=datetime.now(UTC))
            )
            if result.rowcount != 1:
                raise LeadWorkflowError("Подготовка устарела: карточку обрабатывает другой запрос.")
            await ContactEventRepository(session).add(
                lead.contact_id,
                ContactEventType.NOTE_ADDED,
                lead_id=lead.id,
                manager_telegram_id=manager_id,
                payload={
                    "kind": "hot_outreach_prepared",
                    "message_preview": message[:240],
                },
            )
            await session.commit()
        refreshed = await self.detail(lead_id, include_saved_history=True)
        if refreshed is None:
            raise LeadWorkflowError("Лид исчез после подготовки")
        return refreshed

    async def save_draft(
        self,
        lead_id: int,
        manager_id: int,
        message: str,
        *,
        source: str = "manual",
    ) -> dict[str, Any]:
        """Сохранить/обновить текст предложения без GPT (правка менеджера)."""
        async with self._claim(lead_id) as token:
            return await self._save_draft_claimed(
                lead_id, manager_id, message, source=source, claim_token=token
            )

    async def _save_draft_claimed(
        self, lead_id: int, manager_id: int, message: str, *, source: str, claim_token: str
    ) -> dict[str, Any]:
        cleaned = (message or "").strip()
        if not cleaned:
            raise LeadWorkflowError("Текст предложения пустой")
        if len(cleaned) > 4000:
            raise LeadWorkflowError("Текст слишком длинный (макс. 4000 символов)")
        await self._ensure_taken(lead_id, manager_id)
        detail = await self.detail(lead_id)
        if detail is None:
            raise LeadWorkflowError("HOT-лид не найден")
        if detail.get("already_sent") or (detail.get("draft") and detail["draft"].get("sent_at")):
            raise LeadWorkflowError("Предложение уже отмечено как отправленное")
        if detail.get("draft") and detail["draft"].get("message") == cleaned:
            return detail
        recommendation = detail.get("recommendation") or {}
        prepared_at = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
            await self._lock_lead_write(session, lead_id)
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise LeadWorkflowError("Лид не найден")
            details = dict(lead.analysis_details or {})
            existing = dict(details.get(HOT_OUTREACH_KEY) or {})
            existing.update(
                {
                    "message": cleaned,
                    "prepared_at": prepared_at,
                    "prepared_by": manager_id,
                    "recommendation_title": recommendation.get("title"),
                    "product_id": recommendation.get("product_id"),
                    "product_sku": recommendation.get("product_sku"),
                    "source": source,
                    "sent_at": None,
                }
            )
            details[HOT_OUTREACH_KEY] = existing
            result = await session.execute(
                update(Lead)
                .where(*self._editable_write_conditions(lead_id, manager_id, claim_token))
                .values(analysis_details=details, updated_at=datetime.now(UTC))
            )
            if result.rowcount != 1:
                raise LeadWorkflowError(
                    "Карточка изменилась. Обновите её перед сохранением текста."
                )
            await ContactEventRepository(session).add(
                lead.contact_id,
                ContactEventType.NOTE_ADDED,
                lead_id=lead.id,
                manager_telegram_id=manager_id,
                payload={
                    "kind": "hot_outreach_draft_saved",
                    "source": source,
                    "message_preview": cleaned[:240],
                },
            )
            await session.commit()
        refreshed = await self.detail(lead_id, include_saved_history=True)
        if refreshed is None:
            raise LeadWorkflowError("Лид исчез после сохранения текста")
        return refreshed

    async def mark_sent(
        self,
        lead_id: int,
        manager_id: int,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        async with self._claim(lead_id) as token:
            return await self._mark_sent_claimed(
                lead_id, manager_id, message=message, claim_token=token
            )

    async def _mark_sent_claimed(
        self, lead_id: int, manager_id: int, *, message: str | None, claim_token: str
    ) -> dict[str, Any]:
        detail = await self.detail(lead_id, include_saved_history=True)
        if detail is None:
            raise LeadWorkflowError("HOT-лид не найден")
        lead = await self._get_lead(lead_id)
        if lead.assigned_manager_telegram_id not in (None, manager_id):
            raise LeadWorkflowError("Лид уже назначен другому менеджеру")
        draft = detail.get("draft")
        if draft and draft.get("sent_at"):
            if (
                message is not None
                and str(message).strip()
                and str(message).strip() != draft["message"]
            ):
                raise LeadWorkflowError("Отправленный текст нельзя менять повторной отметкой")
            detail["next_lead_id"] = await self.next_queue_lead_id(
                vertical=detail.get("vertical"), exclude_lead_id=lead_id
            )
            return detail
        if message is not None and str(message).strip():
            await self._save_draft_claimed(
                lead_id,
                manager_id,
                str(message),
                source="manual_before_sent",
                claim_token=claim_token,
            )
        detail = await self.detail(lead_id)
        if detail is None:
            raise LeadWorkflowError("HOT-лид не найден")
        draft = detail.get("draft")
        if not draft or not draft.get("message"):
            raise LeadWorkflowError("Сначала подготовьте или вставьте текст предложения")
        if draft.get("sent_at"):
            return detail

        await self._ensure_taken(lead_id, manager_id)
        sent_at = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
            await self._lock_lead_write(session, lead_id)
            stored = await session.get(Lead, lead_id)
            if stored is None:
                raise LeadWorkflowError("Лид не найден")
            self._assert_editable(stored, manager_id)
            # Stages, sent_at and immutable events either all commit or all roll back.
            if stored.status == LeadStatus.TAKEN:
                stored = await self.crm.move_lead_in_session(
                    session, lead_id, manager_id, LeadStatus.CONTACTED
                )
            if stored.status in {LeadStatus.CONTACTED, LeadStatus.QUALIFIED}:
                stored = await self.crm.move_lead_in_session(
                    session, lead_id, manager_id, LeadStatus.OFFER_SENT
                )
            else:
                raise LeadWorkflowError(f"Нельзя отметить отправку со стадии {stored.status.value}")
            details = dict(stored.analysis_details or {})
            outreach = dict(details.get(HOT_OUTREACH_KEY) or {})
            outreach["sent_at"] = sent_at
            outreach["message"] = draft["message"]
            details[HOT_OUTREACH_KEY] = outreach
            result = await session.execute(
                update(Lead)
                .where(
                    Lead.id == lead_id,
                    Lead.outreach_claim_token == claim_token,
                    Lead.status.in_([LeadStatus.OFFER_SENT, LeadStatus.NEGOTIATION]),
                    ~self._sent_clause(Lead),
                )
                .values(analysis_details=details, updated_at=datetime.now(UTC))
            )
            if result.rowcount != 1:
                raise LeadWorkflowError("Карточка изменилась. Обновите её перед отметкой отправки.")
            await ContactEventRepository(session).add(
                stored.contact_id,
                ContactEventType.NOTE_ADDED,
                lead_id=stored.id,
                manager_telegram_id=manager_id,
                payload={
                    "kind": "hot_outreach_sent",
                    "message": draft["message"],
                    "status": stored.status.value,
                },
            )
            await session.commit()
        refreshed = await self.detail(lead_id, include_saved_history=True)
        if refreshed is None:
            raise LeadWorkflowError("Лид исчез после отправки")
        next_id = await self.next_queue_lead_id(
            vertical=refreshed.get("vertical"),
            exclude_lead_id=lead_id,
        )
        refreshed["next_lead_id"] = next_id
        return refreshed

    async def _ensure_taken(self, lead_id: int, manager_id: int) -> Lead:
        lead = await self._get_lead(lead_id)
        self._assert_editable(lead, manager_id)
        if lead.status in {LeadStatus.NEW, LeadStatus.AI_PENDING, LeadStatus.ANALYZING}:
            return await self.workflow.assign_manager(lead_id, manager_id)
        return lead

    def _assert_editable(self, lead: Lead, manager_id: int) -> None:
        if lead.lead_score < self.hot_threshold or not assortment_eligible(lead.analysis_details):
            raise LeadWorkflowError("HOT-лид не найден")
        draft = self._read_draft(lead)
        if draft and draft.sent_at:
            raise LeadWorkflowError("Предложение уже отмечено как отправленное")
        if lead.status not in OPEN_HOT_STATUSES:
            raise LeadWorkflowError(
                "На этой стадии подготовка и изменение HOT-предложения недоступны"
            )
        if lead.assigned_manager_telegram_id not in (None, manager_id):
            raise LeadWorkflowError("Лид уже назначен другому менеджеру")

    def _editable_write_conditions(self, lead_id: int, manager_id: int, claim_token: str):
        return (
            Lead.id == lead_id,
            Lead.outreach_claim_token == claim_token,
            Lead.lead_score >= self.hot_threshold,
            assortment_eligible_clause(Lead),
            Lead.status.in_(OPEN_HOT_STATUSES),
            or_(
                Lead.assigned_manager_telegram_id.is_(None),
                Lead.assigned_manager_telegram_id == manager_id,
            ),
            ~self._sent_clause(Lead),
        )

    @staticmethod
    async def _lock_lead_write(session: AsyncSession, lead_id: int) -> None:
        # SQLite serializes writes; PostgreSQL locks this row. Read JSON afterwards
        # so a simultaneous enrichment cannot be overwritten by a stale merge.
        await session.execute(
            update(Lead).where(Lead.id == lead_id).values(updated_at=Lead.updated_at)
        )

    async def _get_lead(self, lead_id: int) -> Lead:
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise LeadWorkflowError("Лид не найден")
            # detach fields we need
            session.expunge(lead)
            return lead

    @staticmethod
    def _parse_vertical(vertical: str | None) -> Vertical | None:
        if not vertical:
            return None
        try:
            return Vertical(vertical.strip().upper())
        except ValueError:
            return None

    @staticmethod
    def _read_draft(lead: Lead) -> HotOutreachDraft | None:
        payload = (lead.analysis_details or {}).get(HOT_OUTREACH_KEY)
        if not isinstance(payload, dict):
            return None
        message = str(payload.get("message") or "").strip()
        if not message:
            return None
        return HotOutreachDraft(
            message=message,
            prepared_at=str(payload.get("prepared_at") or ""),
            prepared_by=payload.get("prepared_by"),
            recommendation_title=payload.get("recommendation_title"),
            product_id=payload.get("product_id"),
            product_sku=payload.get("product_sku"),
            sent_at=payload.get("sent_at"),
        )

    async def _contact_outreach_summary(
        self,
        session: AsyncSession,
        contact_id: int,
        *,
        exclude_lead_id: int,
    ) -> dict[str, Any]:
        rows = list(
            (
                await session.execute(
                    select(Lead).where(
                        Lead.contact_id == contact_id,
                        Lead.id != exclude_lead_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        prior: list[dict[str, Any]] = []
        for other in rows:
            draft = self._read_draft(other)
            if other.status not in PRIOR_OUTREACH_STATUSES and not (draft and draft.sent_at):
                continue
            prior.append(
                {
                    "lead_id": other.id,
                    "status": other.status.value,
                    "score": other.lead_score,
                    "sent_at": draft.sent_at if draft else None,
                }
            )
        return {
            "already_contacted": bool(prior),
            "prior_count": len(prior),
            "other_leads_count": len(rows),
            "priors": prior[:5],
        }

    @staticmethod
    def _queue_item(
        lead: Lead,
        contact: Contact,
        comment: Comment,
        competitor: Competitor,
        post: Post,
        *,
        already_contacted: bool = False,
    ) -> dict[str, Any]:
        draft = HotOutreachService._read_draft(lead)
        return {
            "lead_id": lead.id,
            "username": contact.username,
            "score": lead.lead_score,
            "status": lead.status.value,
            "intent": lead.intent,
            "product_category": lead.product_category,
            "comment_preview": (comment.text or "")[:160],
            "competitor": competitor.normalized_handle,
            "profile_url": contact.profile_url,
            "post_url": post.url,
            "has_draft": draft is not None,
            "sent": bool(draft and draft.sent_at),
            "already_contacted": already_contacted,
        }
