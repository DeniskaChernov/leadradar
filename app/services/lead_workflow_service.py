from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AIFeedback,
    Comment,
    Competitor,
    Contact,
    ContactEventType,
    Deal,
    DealSaleSnapshot,
    DealStatus,
    Lead,
    LeadStatus,
    NotificationLog,
    NotificationStatus,
    Post,
    Product,
)
from app.db.repositories.events import ContactEventRepository


class LeadWorkflowError(RuntimeError):
    pass


class LeadAlreadyAssignedError(LeadWorkflowError):
    def __init__(self, manager_id: int | None) -> None:
        self.manager_id = manager_id
        super().__init__(f"Lead is already assigned to {manager_id}")


@dataclass(frozen=True, slots=True)
class LeadCard:
    lead_id: int
    contact_id: int
    display_name: str | None
    username: str
    profile_url: str
    comment: str
    competitor: str
    post_caption: str
    post_url: str
    score: int
    intent: str
    product_category: str | None
    ai_reason: str
    status: LeadStatus
    assigned_manager_telegram_id: int | None
    previous_signal_count: int
    recent_signal_count: int


@dataclass(frozen=True, slots=True)
class WorkflowStats:
    contacts: int
    comments: int
    hot_leads: int
    open_leads: int
    won_deals: int
    lost_deals: int
    ai_pending: int
    notification_backlog: int


class LeadWorkflowService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hot_threshold: int,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def assign_manager(
        self, lead_id: int, manager_id: int, *, reassign: bool = False
    ) -> Lead:
        async with self.session_factory() as session:
            result = await session.execute(
                update(Lead)
                .where(
                    Lead.id == lead_id,
                    Lead.assigned_manager_telegram_id.is_(None),
                    Lead.status.in_([LeadStatus.ANALYZING, LeadStatus.AI_PENDING, LeadStatus.NEW]),
                )
                .values(
                    assigned_manager_telegram_id=manager_id,
                    status=LeadStatus.TAKEN,
                    updated_at=datetime.now(UTC),
                )
                .returning(Lead.contact_id)
            )
            contact_id = result.scalar_one_or_none()
            if contact_id is None:
                current = await session.get(Lead, lead_id)
                if current is None:
                    raise LeadWorkflowError("Lead not found")
                if current.assigned_manager_telegram_id == manager_id:
                    return current
                if current.assigned_manager_telegram_id is not None:
                    if not reassign:
                        raise LeadAlreadyAssignedError(current.assigned_manager_telegram_id)
                    previous = current.assigned_manager_telegram_id
                    current.assigned_manager_telegram_id = manager_id
                    if current.status in {
                        LeadStatus.NEW,
                        LeadStatus.AI_PENDING,
                        LeadStatus.ANALYZING,
                    }:
                        current.status = LeadStatus.TAKEN
                    current.updated_at = datetime.now(UTC)
                    await session.execute(
                        update(Contact)
                        .where(Contact.id == current.contact_id)
                        .values(assigned_manager_telegram_id=manager_id)
                    )
                    feedback = await session.scalar(
                        select(AIFeedback).where(AIFeedback.lead_id == lead_id)
                    )
                    if feedback is not None:
                        feedback.manager_is_lead = True
                    await ContactEventRepository(session).add(
                        current.contact_id,
                        ContactEventType.MANAGER_ASSIGNED,
                        lead_id=lead_id,
                        manager_telegram_id=manager_id,
                        payload={
                            "manager_telegram_id": manager_id,
                            "reassign_from": previous,
                        },
                    )
                    await session.commit()
                    lead = await session.get(Lead, lead_id)
                    if lead is None:
                        raise RuntimeError("Assigned lead disappeared")
                    return lead
                raise LeadWorkflowError(f"Lead cannot be taken in status {current.status.value}")
            await session.execute(
                update(Contact)
                .where(Contact.id == contact_id)
                .values(assigned_manager_telegram_id=manager_id)
            )
            feedback = await session.scalar(
                select(AIFeedback).where(AIFeedback.lead_id == lead_id)
            )
            if feedback is not None:
                feedback.manager_is_lead = True
            await ContactEventRepository(session).add(
                contact_id,
                ContactEventType.MANAGER_ASSIGNED,
                lead_id=lead_id,
                manager_telegram_id=manager_id,
                payload={"manager_telegram_id": manager_id},
            )
            await session.commit()
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise RuntimeError("Assigned lead disappeared")
            return lead

    async def mark_not_lead(self, lead_id: int, manager_id: int) -> Lead:
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise LeadWorkflowError("Lead not found")
            if lead.status == LeadStatus.NOT_LEAD:
                return lead
            if (
                lead.assigned_manager_telegram_id is not None
                and lead.assigned_manager_telegram_id != manager_id
            ):
                raise LeadAlreadyAssignedError(lead.assigned_manager_telegram_id)
            if lead.status in {LeadStatus.WON, LeadStatus.LOST}:
                raise LeadWorkflowError(f"Closed lead cannot become NOT_LEAD: {lead.status.value}")
            lead.status = LeadStatus.NOT_LEAD
            feedback = await session.scalar(
                select(AIFeedback).where(AIFeedback.lead_id == lead_id)
            )
            if feedback is not None:
                feedback.manager_is_lead = False
                feedback.actual_outcome = LeadStatus.NOT_LEAD.value
            await ContactEventRepository(session).add(
                lead.contact_id,
                ContactEventType.MANAGER_MARKED_NOT_LEAD,
                lead_id=lead.id,
                manager_telegram_id=manager_id,
            )
            await session.commit()
            return lead

    async def create_deal(self, lead_id: int, manager_id: int) -> Deal:
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise LeadWorkflowError("Lead not found")
            if (
                lead.assigned_manager_telegram_id is not None
                and lead.assigned_manager_telegram_id != manager_id
            ):
                raise LeadAlreadyAssignedError(lead.assigned_manager_telegram_id)
            if lead.status != LeadStatus.TAKEN:
                raise LeadWorkflowError("A deal can be created only for a TAKEN lead")
            deal = await session.scalar(
                select(Deal).where(
                    Deal.lead_id == lead_id,
                    Deal.status.not_in([DealStatus.WON, DealStatus.LOST]),
                )
            )
            if deal is not None:
                return deal
            deal = Deal(
                contact_id=lead.contact_id,
                lead_id=lead.id,
                manager_telegram_id=manager_id,
                status=DealStatus.NEW,
                product_category=lead.product_category,
            )
            session.add(deal)
            try:
                await session.flush()
                feedback = await session.scalar(
                    select(AIFeedback).where(AIFeedback.lead_id == lead_id)
                )
                if feedback is not None:
                    feedback.deal_created = True
                await ContactEventRepository(session).add(
                    lead.contact_id,
                    ContactEventType.DEAL_CREATED,
                    lead_id=lead.id,
                    deal_id=deal.id,
                    manager_telegram_id=manager_id,
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(Deal).where(Deal.lead_id == lead_id)
                )
                if existing is None:
                    raise
                return existing
            return deal

    async def win_deal(
        self,
        deal_id: int,
        manager_id: int,
        *,
        product_name: str,
        amount: Decimal,
        quantity: int,
        product_id: int | None = None,
        sale_currency: str = "UZS",
    ) -> Deal:
        cleaned_product = product_name.strip()
        if not cleaned_product and product_id is None:
            raise LeadWorkflowError("Product name is required")
        if not amount.is_finite() or amount <= 0:
            raise LeadWorkflowError("Deal amount must be positive")
        if quantity <= 0:
            raise LeadWorkflowError("Deal quantity must be positive")
        normalized_currency = sale_currency.strip().upper()
        if not normalized_currency or len(normalized_currency) > 8:
            raise LeadWorkflowError("Sale currency is invalid")
        async with self.session_factory() as session:
            deal, lead = await self._load_deal_and_lead(
                session,
                deal_id,
                manager_id,
                allow_closed=True,
            )
            product = None
            if product_id is not None:
                product = await session.get(Product, product_id)
                if product is None or not product.active:
                    raise LeadWorkflowError("Active catalog product not found")
                cleaned_product = product.name
            if deal.status == DealStatus.WON:
                snapshot = await session.scalar(
                    select(DealSaleSnapshot).where(DealSaleSnapshot.deal_id == deal.id)
                )
                if snapshot is not None and (
                    snapshot.product_id == product_id
                    and snapshot.product_name == cleaned_product
                    and snapshot.sale_amount == amount
                    and snapshot.quantity == quantity
                    and snapshot.sale_currency == normalized_currency
                ):
                    return deal
                raise LeadWorkflowError("Won deal cannot be changed by a repeated request")
            if deal.status == DealStatus.LOST:
                raise LeadWorkflowError("Lost deal cannot become WON")
            now = datetime.now(UTC)
            deal.status = DealStatus.WON
            deal.product_id = product.id if product is not None else None
            deal.product_name = cleaned_product
            deal.amount = amount
            deal.final_amount = amount
            deal.quantity = quantity
            deal.won_at = now
            lead.status = LeadStatus.WON
            feedback = await session.scalar(
                select(AIFeedback).where(AIFeedback.lead_id == lead.id)
            )
            if feedback is not None:
                feedback.actual_outcome = DealStatus.WON.value
                feedback.deal_created = True
                feedback.deal_won = True
                feedback.deal_amount = amount
            evidence_ids = tuple((lead.analysis_details or {}).get("evidence_ids") or ())
            session.add(
                DealSaleSnapshot(
                    deal_id=deal.id,
                    product_id=product.id if product is not None else None,
                    product_canonical_key=(
                        product.canonical_key if product is not None else None
                    ),
                    product_name=cleaned_product,
                    sku=product.sku if product is not None else None,
                    category=(
                        product.category
                        if product is not None and product.category_confirmed_at is not None
                        else (deal.product_category if product is None else None)
                    ),
                    catalog_price=(
                        product.price
                        if product is not None and product.price_confirmed_at is not None
                        else None
                    ),
                    catalog_currency=(
                        product.currency
                        if product is not None and product.price_confirmed_at is not None
                        else None
                    ),
                    cogs=(
                        product.cogs
                        if product is not None and product.cogs_confirmed_at is not None
                        else None
                    ),
                    quantity=quantity,
                    sale_amount=amount,
                    sale_currency=normalized_currency,
                    catalog_version=product.catalog_version if product is not None else None,
                    evidence_ids_json=list(evidence_ids),
                    manager_telegram_id=manager_id,
                )
            )
            await ContactEventRepository(session).add(
                deal.contact_id,
                ContactEventType.DEAL_WON,
                lead_id=lead.id,
                deal_id=deal.id,
                manager_telegram_id=manager_id,
                payload={
                    "amount": str(amount),
                    "quantity": quantity,
                    "product": cleaned_product,
                    "product_id": product.id if product is not None else None,
                },
            )
            await session.commit()
            return deal

    async def lose_deal(self, deal_id: int, manager_id: int, *, reason: str) -> Deal:
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise LeadWorkflowError("Lost reason is required")
        async with self.session_factory() as session:
            deal, lead = await self._load_deal_and_lead(
                session,
                deal_id,
                manager_id,
                allow_closed=True,
            )
            if deal.status == DealStatus.LOST:
                if deal.lost_reason == cleaned_reason:
                    return deal
                raise LeadWorkflowError("Lost deal reason cannot be changed by a repeated request")
            if deal.status == DealStatus.WON:
                raise LeadWorkflowError("Won deal cannot become LOST")
            deal.status = DealStatus.LOST
            deal.lost_reason = cleaned_reason
            deal.lost_at = datetime.now(UTC)
            lead.status = LeadStatus.LOST
            feedback = await session.scalar(
                select(AIFeedback).where(AIFeedback.lead_id == lead.id)
            )
            if feedback is not None:
                feedback.actual_outcome = DealStatus.LOST.value
                feedback.deal_created = True
                feedback.deal_won = False
                feedback.lost_reason = cleaned_reason
            await ContactEventRepository(session).add(
                deal.contact_id,
                ContactEventType.DEAL_LOST,
                lead_id=lead.id,
                deal_id=deal.id,
                manager_telegram_id=manager_id,
                payload={"reason": cleaned_reason},
            )
            await session.commit()
            return deal

    async def get_lead_card(self, lead_id: int) -> LeadCard:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(Lead, Contact, Comment, Post, Competitor)
                    .join(Contact, Lead.contact_id == Contact.id)
                    .join(Comment, Lead.comment_id == Comment.id)
                    .join(Post, Comment.post_id == Post.id)
                    .join(Competitor, Lead.competitor_id == Competitor.id)
                    .where(Lead.id == lead_id)
                )
            ).one_or_none()
            if row is None:
                raise LeadWorkflowError("Lead not found")
            lead, contact, comment, post, competitor = row
            total_signals = await session.scalar(
                select(func.count(Comment.id)).where(Comment.contact_id == contact.id)
            )
            recent_signals = await session.scalar(
                select(func.count(Comment.id)).where(
                    Comment.contact_id == contact.id,
                    Comment.discovered_at >= datetime.now(UTC) - timedelta(days=14),
                )
            )
            return LeadCard(
                lead_id=lead.id,
                contact_id=contact.id,
                display_name=contact.display_name,
                username=contact.username,
                profile_url=contact.profile_url,
                comment=comment.text,
                competitor=competitor.normalized_handle,
                post_caption=post.caption,
                post_url=post.url,
                score=lead.lead_score,
                intent=lead.intent,
                product_category=lead.product_category,
                ai_reason=lead.ai_reason,
                status=lead.status,
                assigned_manager_telegram_id=lead.assigned_manager_telegram_id,
                previous_signal_count=max(0, (total_signals or 0) - 1),
                recent_signal_count=max(0, (recent_signals or 0) - 1),
            )

    async def list_hot_leads(self, limit: int = 10) -> list[LeadCard]:
        async with self.session_factory() as session:
            ids = (
                await session.scalars(
                    select(Lead.id)
                    .where(
                        Lead.lead_score >= self.hot_threshold,
                        Lead.status.in_([LeadStatus.NEW, LeadStatus.TAKEN]),
                    )
                    .order_by(Lead.created_at.desc())
                    .limit(limit)
                )
            ).all()
        return [await self.get_lead_card(lead_id) for lead_id in ids]

    async def list_ai_pending_leads(self, limit: int = 10) -> list[LeadCard]:
        async with self.session_factory() as session:
            ids = (
                await session.scalars(
                    select(Lead.id)
                    .where(Lead.status == LeadStatus.AI_PENDING)
                    .order_by(Lead.created_at)
                    .limit(limit)
                )
            ).all()
        cards: list[LeadCard] = []
        for lead_id in ids:
            with contextlib.suppress(LeadWorkflowError):
                cards.append(await self.get_lead_card(lead_id))
        return cards

    async def get_stats(self) -> WorkflowStats:
        async with self.session_factory() as session:
            contacts = await session.scalar(select(func.count(Contact.id))) or 0
            comments = await session.scalar(select(func.count(Comment.id))) or 0
            hot = (
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.lead_score >= self.hot_threshold
                    )
                )
                or 0
            )
            open_leads = (
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.status.in_([LeadStatus.NEW, LeadStatus.TAKEN])
                    )
                )
                or 0
            )
            won = (
                await session.scalar(
                    select(func.count(Deal.id)).where(Deal.status == DealStatus.WON)
                )
                or 0
            )
            lost = (
                await session.scalar(
                    select(func.count(Deal.id)).where(Deal.status == DealStatus.LOST)
                )
                or 0
            )
            ai_pending = (
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.status.in_([LeadStatus.ANALYZING, LeadStatus.AI_PENDING])
                    )
                )
                or 0
            )
            notification_backlog = (
                await session.scalar(
                    select(func.count(NotificationLog.id)).where(
                        NotificationLog.status != NotificationStatus.SENT
                    )
                )
                or 0
            )
            return WorkflowStats(
                contacts=contacts,
                comments=comments,
                hot_leads=hot,
                open_leads=open_leads,
                won_deals=won,
                lost_deals=lost,
                ai_pending=ai_pending,
                notification_backlog=notification_backlog,
            )

    async def _load_deal_and_lead(
        self,
        session: AsyncSession,
        deal_id: int,
        manager_id: int,
        *,
        allow_closed: bool = False,
    ) -> tuple[Deal, Lead]:
        deal = await session.get(Deal, deal_id)
        if deal is None or deal.lead_id is None:
            raise LeadWorkflowError("Deal not found")
        if deal.manager_telegram_id not in (None, manager_id):
            raise LeadAlreadyAssignedError(deal.manager_telegram_id)
        lead = await session.get(Lead, deal.lead_id)
        if lead is None:
            raise LeadWorkflowError("Lead for deal not found")
        if not allow_closed and deal.status in {DealStatus.WON, DealStatus.LOST}:
            raise LeadWorkflowError("Deal is already closed")
        return deal, lead
