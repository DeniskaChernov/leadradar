from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AIFeedback,
    Comment,
    Competitor,
    Contact,
    ContactEventType,
    Deal,
    DealStatus,
    Lead,
    LeadStatus,
    Post,
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


class LeadWorkflowService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        hot_threshold: int,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def assign_manager(self, lead_id: int, manager_id: int) -> Lead:
        async with self.session_factory() as session:
            result = await session.execute(
                update(Lead)
                .where(
                    Lead.id == lead_id,
                    Lead.assigned_manager_telegram_id.is_(None),
                    Lead.status == LeadStatus.NEW,
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
                    raise LeadAlreadyAssignedError(current.assigned_manager_telegram_id)
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
            return deal

    async def win_deal(
        self,
        deal_id: int,
        manager_id: int,
        *,
        product_name: str,
        amount: Decimal,
        quantity: int,
    ) -> Deal:
        async with self.session_factory() as session:
            deal, lead = await self._load_deal_and_lead(session, deal_id, manager_id)
            now = datetime.now(UTC)
            deal.status = DealStatus.WON
            deal.product_name = product_name
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
            await ContactEventRepository(session).add(
                deal.contact_id,
                ContactEventType.DEAL_WON,
                lead_id=lead.id,
                deal_id=deal.id,
                manager_telegram_id=manager_id,
                payload={"amount": str(amount), "quantity": quantity, "product": product_name},
            )
            await session.commit()
            return deal

    async def lose_deal(self, deal_id: int, manager_id: int, *, reason: str) -> Deal:
        async with self.session_factory() as session:
            deal, lead = await self._load_deal_and_lead(session, deal_id, manager_id)
            deal.status = DealStatus.LOST
            deal.lost_reason = reason
            deal.lost_at = datetime.now(UTC)
            lead.status = LeadStatus.LOST
            feedback = await session.scalar(
                select(AIFeedback).where(AIFeedback.lead_id == lead.id)
            )
            if feedback is not None:
                feedback.actual_outcome = DealStatus.LOST.value
                feedback.deal_created = True
                feedback.deal_won = False
                feedback.lost_reason = reason
            await ContactEventRepository(session).add(
                deal.contact_id,
                ContactEventType.DEAL_LOST,
                lead_id=lead.id,
                deal_id=deal.id,
                manager_telegram_id=manager_id,
                payload={"reason": reason},
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
            return WorkflowStats(contacts, comments, hot, open_leads, won, lost)

    async def _load_deal_and_lead(
        self, session: AsyncSession, deal_id: int, manager_id: int
    ) -> tuple[Deal, Lead]:
        deal = await session.get(Deal, deal_id)
        if deal is None or deal.lead_id is None:
            raise LeadWorkflowError("Deal not found")
        if deal.manager_telegram_id not in (None, manager_id):
            raise LeadAlreadyAssignedError(deal.manager_telegram_id)
        lead = await session.get(Lead, deal.lead_id)
        if lead is None:
            raise LeadWorkflowError("Lead for deal not found")
        if deal.status in {DealStatus.WON, DealStatus.LOST}:
            raise LeadWorkflowError("Deal is already closed")
        return deal, lead
