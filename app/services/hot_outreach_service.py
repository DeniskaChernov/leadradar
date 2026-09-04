"""HOT outreach: черновик Instagram DM + движение по воронке после отправки."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Comment,
    Competitor,
    Contact,
    ContactEventType,
    Lead,
    LeadStatus,
    Post,
    Vertical,
)
from app.db.repositories.events import ContactEventRepository
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadWorkflowError, LeadWorkflowService
from app.services.product_catalog_service import ProductCatalogService
from app.services.usage_service import ExternalUsageService

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

    def __init__(self, text: str = "Здравствуйте! Могу предложить подходящий вариант из каталога.") -> None:
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

            self.client = AsyncOpenAI(api_key=api_key)

    async def compose(self, context: dict[str, Any]) -> str:
        instructions = (
            "Ты помощник менеджера Lead Radar. Напиши одно короткое личное сообщение "
            "для Instagram Direct по фактам из JSON. Только текст сообщения, без кавычек, "
            "без markdown, без пояснений. 2–5 предложений. Язык = язык комментария клиента "
            "(русский / узбекский / смешанный). Не выдумывай цены, наличие и свойства, "
            "которых нет во входных данных. Если товара нет — мягко уточни потребность. "
            "Не проси телефон/email. Не упоминай, что ты ИИ."
        )
        response = await self.client.responses.create(
            model=self.model,
            instructions=instructions,
            input=json.dumps(context, ensure_ascii=False, default=str),
            max_output_tokens=500,
            store=False,
            prompt_cache_key="lead-radar-hot-outreach-v1",
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
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold
        self.workflow = workflow
        self.crm = crm
        self.catalog = catalog
        self.usage = usage
        self.composer = composer
        self.openai_daily_limit = openai_daily_limit

    async def queue(
        self,
        *,
        vertical: str | None = None,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        vertical_enum = self._parse_vertical(vertical)
        async with self.session_factory() as session:
            stmt = (
                select(Lead, Contact, Comment, Competitor, Post)
                .join(Contact, Contact.id == Lead.contact_id)
                .join(Comment, Comment.id == Lead.comment_id)
                .join(Competitor, Competitor.id == Lead.competitor_id)
                .join(Post, Post.id == Comment.post_id)
                .where(
                    Lead.lead_score >= self.hot_threshold,
                    Lead.status.in_(OPEN_HOT_STATUSES),
                )
                .order_by(desc(Lead.lead_score), desc(Lead.created_at))
                .limit(limit)
            )
            if vertical_enum is not None:
                stmt = stmt.where(Lead.vertical == vertical_enum)
            rows = (await session.execute(stmt)).all()
            priors = await self._prior_outreach_leads_by_contact(
                session,
                {contact.id for _lead, contact, *_rest in rows},
            )
        return [
            self._queue_item(
                lead,
                contact,
                comment,
                competitor,
                post,
                already_contacted=bool(
                    priors.get(contact.id, set()) - {lead.id}
                ),
            )
            for lead, contact, comment, competitor, post in rows
        ]

    async def next_queue_lead_id(
        self,
        *,
        vertical: str | None = None,
        exclude_lead_id: int | None = None,
    ) -> int | None:
        """Следующий HOT после текущего — для непрерывного дневного цикла."""
        for item in await self.queue(vertical=vertical, limit=80):
            if exclude_lead_id is not None and item["lead_id"] == exclude_lead_id:
                continue
            if item.get("sent"):
                continue
            return int(item["lead_id"])
        return None

    async def detail(
        self,
        lead_id: int,
        *,
        vertical: str | None = None,
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
            if lead.lead_score < self.hot_threshold:
                return None
            contact_history = await self._contact_outreach_summary(
                session, contact.id, exclude_lead_id=lead.id
            )
        recommendation = await self.catalog.recommend_for_lead(lead)
        draft = self._read_draft(lead)
        return {
            "lead_id": lead.id,
            "status": lead.status.value,
            "score": lead.lead_score,
            "intent": lead.intent,
            "product_category": lead.product_category,
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
            "can_mark_sent": draft is not None and draft.sent_at is None,
            "already_sent": draft is not None and draft.sent_at is not None,
            "contact_history": contact_history,
        }

    async def prepare(
        self,
        lead_id: int,
        manager_id: int,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        if self.composer is None:
            raise LeadWorkflowError(
                "Подготовка текста недоступна: OpenAI выключен. "
                "Включите тумблер OpenAI в системе."
            )
        await self._ensure_taken(lead_id, manager_id)
        detail = await self.detail(lead_id)
        if detail is None:
            raise LeadWorkflowError("HOT-лид не найден")
        existing = detail.get("draft")
        if existing and existing.get("message") and not force and not existing.get("sent_at"):
            return detail

        context = {
            "username": detail["username"],
            "comment_text": detail["comment_text"],
            "language": detail["language"],
            "intent": detail["intent"],
            "product_category": detail["product_category"],
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
            reservation_id = await self.usage.reserve_budget(
                "openai",
                "hot_outreach_compose",
                self.openai_daily_limit,
                units=1,
                estimated_cost=0.0,
                request_fingerprint=f"hot-outreach:{lead_id}:{force}",
                worker_id="hot-outreach",
                provider="openai",
            )
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
                    units=0,
                    success=False,
                    details={"operation": "hot_outreach_compose_failed"},
                    lead_id=lead_id,
                )
            raise
        except Exception as exc:
            logger.exception("hot_outreach_compose_failed lead_id=%s", lead_id)
            if reservation_id is not None and self.usage is not None:
                await self.usage.finalize_reservation(
                    reservation_id,
                    units=0,
                    success=False,
                    details={"operation": "hot_outreach_compose_failed"},
                    lead_id=lead_id,
                )
            raise LeadWorkflowError("Не удалось подготовить текст через OpenAI") from exc

        prepared_at = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
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
            lead.analysis_details = details
            lead.updated_at = datetime.now(UTC)
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
        refreshed = await self.detail(lead_id)
        if refreshed is None:
            raise LeadWorkflowError("Лид исчез после подготовки")
        return refreshed

    async def mark_sent(self, lead_id: int, manager_id: int) -> dict[str, Any]:
        detail = await self.detail(lead_id)
        if detail is None:
            raise LeadWorkflowError("HOT-лид не найден")
        draft = detail.get("draft")
        if not draft or not draft.get("message"):
            raise LeadWorkflowError("Сначала подготовьте текст предложения")
        if draft.get("sent_at"):
            return detail

        await self._ensure_taken(lead_id, manager_id)
        lead = await self._get_lead(lead_id)
        # TAKEN → CONTACTED → OFFER_SENT одной командой «Отправил».
        if lead.status == LeadStatus.TAKEN:
            lead = await self.crm.move_lead(lead_id, manager_id, LeadStatus.CONTACTED)
        if lead.status in {LeadStatus.CONTACTED, LeadStatus.QUALIFIED}:
            lead = await self.crm.move_lead(lead_id, manager_id, LeadStatus.OFFER_SENT)
        elif lead.status == LeadStatus.OFFER_SENT:
            pass
        elif lead.status == LeadStatus.NEGOTIATION:
            pass
        else:
            raise LeadWorkflowError(
                f"Нельзя отметить отправку со стадии {lead.status.value}"
            )

        sent_at = datetime.now(UTC).isoformat()
        async with self.session_factory() as session:
            stored = await session.get(Lead, lead_id)
            if stored is None:
                raise LeadWorkflowError("Лид не найден")
            details = dict(stored.analysis_details or {})
            outreach = dict(details.get(HOT_OUTREACH_KEY) or {})
            outreach["sent_at"] = sent_at
            outreach["message"] = draft["message"]
            details[HOT_OUTREACH_KEY] = outreach
            stored.analysis_details = details
            stored.updated_at = datetime.now(UTC)
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
        refreshed = await self.detail(lead_id)
        if refreshed is None:
            raise LeadWorkflowError("Лид исчез после отправки")
        refreshed["status"] = lead.status.value
        next_id = await self.next_queue_lead_id(
            vertical=refreshed.get("vertical"),
            exclude_lead_id=lead_id,
        )
        refreshed["next_lead_id"] = next_id
        return refreshed

    async def _ensure_taken(self, lead_id: int, manager_id: int) -> Lead:
        lead = await self._get_lead(lead_id)
        if lead.status in {LeadStatus.NEW, LeadStatus.AI_PENDING, LeadStatus.ANALYZING}:
            return await self.workflow.assign_manager(lead_id, manager_id)
        if lead.assigned_manager_telegram_id in (None, manager_id):
            return lead
        raise LeadWorkflowError("Лид уже назначен другому менеджеру")

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

    async def _prior_outreach_leads_by_contact(
        self,
        session: AsyncSession,
        contact_ids: set[int],
    ) -> dict[int, set[int]]:
        """contact_id → lead_id, по которым уже был outreach / стадия после контакта."""
        if not contact_ids:
            return {}
        rows = (
            await session.execute(
                select(Lead.contact_id, Lead.id, Lead.status, Lead.analysis_details).where(
                    Lead.contact_id.in_(contact_ids)
                )
            )
        ).all()
        result: dict[int, set[int]] = {contact_id: set() for contact_id in contact_ids}
        for contact_id, lead_id, status, details in rows:
            draft_payload = (details or {}).get(HOT_OUTREACH_KEY)
            sent = isinstance(draft_payload, dict) and bool(draft_payload.get("sent_at"))
            if status in PRIOR_OUTREACH_STATUSES or sent:
                result.setdefault(contact_id, set()).add(lead_id)
        return result

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
            ).scalars().all()
        )
        prior: list[dict[str, Any]] = []
        for other in rows:
            draft = self._read_draft(other)
            if other.status not in PRIOR_OUTREACH_STATUSES and not (
                draft and draft.sent_at
            ):
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
