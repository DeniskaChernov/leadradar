from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import normalize_instagram_handle
from app.db.models import (
    AIFeedback,
    BusinessEntity,
    Competitor,
    Contact,
    ContactEventType,
    ContactTask,
    Deal,
    DealStatus,
    Lead,
    LeadStatus,
    NotificationPolicy,
    TaskStatus,
    Vertical,
)
from app.db.repositories.events import ContactEventRepository
from app.services.lead_workflow_service import LeadAlreadyAssignedError, LeadWorkflowError
from app.services.rattan_vertical_service import sync_business_vertical_enrollment

ALLOWED_STAGE_TRANSITIONS: dict[LeadStatus, set[LeadStatus]] = {
    LeadStatus.ANALYZING: {LeadStatus.TAKEN, LeadStatus.NOT_LEAD},
    LeadStatus.NEW: {LeadStatus.TAKEN, LeadStatus.NOT_LEAD},
    LeadStatus.TAKEN: {LeadStatus.CONTACTED, LeadStatus.QUALIFIED, LeadStatus.LOST, LeadStatus.NOT_LEAD},
    LeadStatus.CONTACTED: {LeadStatus.QUALIFIED, LeadStatus.OFFER_SENT, LeadStatus.NEGOTIATION, LeadStatus.LOST},
    LeadStatus.QUALIFIED: {LeadStatus.OFFER_SENT, LeadStatus.NEGOTIATION, LeadStatus.LOST},
    LeadStatus.OFFER_SENT: {LeadStatus.NEGOTIATION, LeadStatus.WON, LeadStatus.LOST},
    LeadStatus.NEGOTIATION: {LeadStatus.OFFER_SENT, LeadStatus.WON, LeadStatus.LOST},
    LeadStatus.AI_PENDING: {LeadStatus.TAKEN, LeadStatus.NOT_LEAD},
    LeadStatus.WON: set(),
    LeadStatus.LOST: set(),
    LeadStatus.NOT_LEAD: set(),
}


class CRMService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def move_lead(self, lead_id: int, manager_id: int, target: LeadStatus) -> Lead:
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise LeadWorkflowError("Лид не найден")
            if lead.assigned_manager_telegram_id not in (None, manager_id):
                raise LeadAlreadyAssignedError(lead.assigned_manager_telegram_id)
            if target == lead.status:
                return lead
            allowed = ALLOWED_STAGE_TRANSITIONS.get(lead.status, set())
            if target not in allowed:
                raise LeadWorkflowError(
                    f"Нельзя перейти со стадии {lead.status.value} на {target.value}"
                )
            previous = lead.status
            lead.status = target
            contact = await session.get(Contact, lead.contact_id)
            if lead.assigned_manager_telegram_id is None and target not in {LeadStatus.NOT_LEAD}:
                lead.assigned_manager_telegram_id = manager_id
                if contact is not None:
                    contact.assigned_manager_telegram_id = manager_id
            if target == LeadStatus.CONTACTED and contact is not None:
                contact.last_contacted_at = datetime.now(UTC)
            event_type = {
                LeadStatus.CONTACTED: ContactEventType.CONTACTED,
                LeadStatus.OFFER_SENT: ContactEventType.OFFER_SENT,
                LeadStatus.NEGOTIATION: ContactEventType.NEGOTIATION_STARTED,
            }.get(target, ContactEventType.LEAD_STATUS_CHANGED)
            await ContactEventRepository(session).add(
                lead.contact_id,
                event_type,
                lead_id=lead.id,
                manager_telegram_id=manager_id,
                payload={"from": previous.value, "to": target.value},
            )
            await session.commit()
            return lead

    async def record_customer_reply(
        self,
        contact_id: int,
        manager_id: int,
        *,
        text: str = "",
        lead_id: int | None = None,
    ) -> None:
        cleaned = text.strip()
        async with self.session_factory() as session:
            contact = await session.get(Contact, contact_id)
            if contact is None:
                raise LeadWorkflowError("Клиент не найден")
            if lead_id is not None:
                lead = await session.get(Lead, lead_id)
                if lead is None or lead.contact_id != contact_id:
                    raise LeadWorkflowError("Лид не принадлежит этому клиенту")
            contact.last_contacted_at = datetime.now(UTC)
            await ContactEventRepository(session).add(
                contact_id,
                ContactEventType.CUSTOMER_REPLIED,
                lead_id=lead_id,
                manager_telegram_id=manager_id,
                payload={"text": cleaned} if cleaned else {},
            )
            await session.commit()

    async def update_contact_qualification(
        self,
        contact_id: int,
        manager_id: int,
        *,
        phone: str | None = None,
        preferred_channel: str | None = None,
        city: str | None = None,
        interest_summary: str | None = None,
        desired_quantity: int | None = None,
        budget_from: Decimal | None = None,
        budget_to: Decimal | None = None,
        desired_color: str | None = None,
        purchase_timeline: str | None = None,
        qualification_note: str | None = None,
    ) -> Contact:
        if desired_quantity is not None and desired_quantity <= 0:
            raise LeadWorkflowError("Количество должно быть больше нуля")
        if budget_from is not None and budget_from < 0:
            raise LeadWorkflowError("Минимальный бюджет не может быть отрицательным")
        if budget_to is not None and budget_to < 0:
            raise LeadWorkflowError("Максимальный бюджет не может быть отрицательным")
        if budget_from is not None and budget_to is not None and budget_from > budget_to:
            raise LeadWorkflowError("Минимальный бюджет не может быть больше максимального")

        allowed_channels = {"", "instagram", "telegram", "phone", "whatsapp", "other"}
        normalized_channel = (preferred_channel or "").strip().lower()
        if normalized_channel not in allowed_channels:
            raise LeadWorkflowError("Неизвестный канал связи")

        async with self.session_factory() as session:
            contact = await session.get(Contact, contact_id)
            if contact is None:
                raise LeadWorkflowError("Клиент не найден")

            before = {
                "phone": contact.phone,
                "preferred_channel": contact.preferred_channel,
                "city": contact.city,
                "interest_summary": contact.interest_summary,
                "desired_quantity": contact.desired_quantity,
                "budget_from": str(contact.budget_from) if contact.budget_from is not None else None,
                "budget_to": str(contact.budget_to) if contact.budget_to is not None else None,
                "desired_color": contact.desired_color,
                "purchase_timeline": contact.purchase_timeline,
                "qualification_note": contact.qualification_note,
            }

            contact.phone = _clean_optional(phone, 64)
            contact.preferred_channel = normalized_channel or None
            contact.city = _clean_optional(city, 128)
            contact.interest_summary = _clean_optional(interest_summary, 255)
            contact.desired_quantity = desired_quantity
            contact.budget_from = budget_from
            contact.budget_to = budget_to
            contact.desired_color = _clean_optional(desired_color, 128)
            contact.purchase_timeline = _clean_optional(purchase_timeline, 128)
            contact.qualification_note = _clean_optional(qualification_note, 4000)
            contact.qualification_updated_at = datetime.now(UTC)

            after = {
                "phone": contact.phone,
                "preferred_channel": contact.preferred_channel,
                "city": contact.city,
                "interest_summary": contact.interest_summary,
                "desired_quantity": contact.desired_quantity,
                "budget_from": str(contact.budget_from) if contact.budget_from is not None else None,
                "budget_to": str(contact.budget_to) if contact.budget_to is not None else None,
                "desired_color": contact.desired_color,
                "purchase_timeline": contact.purchase_timeline,
                "qualification_note": contact.qualification_note,
            }
            changed = {key: value for key, value in after.items() if before.get(key) != value}
            if changed:
                await ContactEventRepository(session).add(
                    contact_id,
                    ContactEventType.QUALIFICATION_UPDATED,
                    manager_telegram_id=manager_id,
                    payload={"changed": changed},
                )
            await session.commit()
            return contact

    async def add_note(self, contact_id: int, manager_id: int, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            raise LeadWorkflowError("Заметка не может быть пустой")
        if len(cleaned) > 4000:
            raise LeadWorkflowError("Заметка слишком длинная")
        async with self.session_factory() as session:
            if await session.get(Contact, contact_id) is None:
                raise LeadWorkflowError("Клиент не найден")
            await ContactEventRepository(session).add(
                contact_id,
                ContactEventType.NOTE_ADDED,
                manager_telegram_id=manager_id,
                payload={"text": cleaned},
            )
            await session.commit()

    async def schedule_contact(
        self,
        contact_id: int,
        manager_id: int,
        *,
        due_at: datetime,
        note: str,
        lead_id: int | None = None,
    ) -> ContactTask:
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=UTC)
        async with self.session_factory() as session:
            contact = await session.get(Contact, contact_id)
            if contact is None:
                raise LeadWorkflowError("Клиент не найден")
            if lead_id is not None:
                lead = await session.get(Lead, lead_id)
                if lead is None or lead.contact_id != contact_id:
                    raise LeadWorkflowError("Лид не принадлежит этому клиенту")
            existing = await session.scalar(
                select(ContactTask).where(
                    ContactTask.contact_id == contact_id,
                    ContactTask.lead_id == lead_id,
                    ContactTask.manager_telegram_id == manager_id,
                    ContactTask.due_at == due_at,
                    ContactTask.note == note.strip(),
                    ContactTask.status == TaskStatus.OPEN,
                )
            )
            if existing is not None:
                return existing
            task = ContactTask(
                contact_id=contact_id,
                lead_id=lead_id,
                manager_telegram_id=manager_id,
                due_at=due_at,
                note=note.strip(),
                status=TaskStatus.OPEN,
            )
            session.add(task)
            if lead_id is not None:
                lead.next_action_at = due_at
                lead.next_action_note = note.strip()
            await session.flush()
            await ContactEventRepository(session).add(
                contact_id,
                ContactEventType.NEXT_CONTACT_SCHEDULED,
                lead_id=lead_id,
                manager_telegram_id=manager_id,
                payload={"task_id": task.id, "due_at": due_at.isoformat(), "note": note.strip()},
            )
            await session.commit()
            return task

    async def complete_task(self, task_id: int, manager_id: int) -> ContactTask:
        async with self.session_factory() as session:
            task = await session.get(ContactTask, task_id)
            if task is None:
                raise LeadWorkflowError("Задача не найдена")
            if task.manager_telegram_id not in (None, manager_id):
                raise LeadAlreadyAssignedError(task.manager_telegram_id)
            if task.status == TaskStatus.DONE:
                return task
            task.status = TaskStatus.DONE
            task.completed_at = datetime.now(UTC)
            if task.lead_id:
                lead = await session.get(Lead, task.lead_id)
                if lead is not None and lead.next_action_at == task.due_at:
                    lead.next_action_at = None
                    lead.next_action_note = None
            await ContactEventRepository(session).add(
                task.contact_id,
                ContactEventType.NEXT_CONTACT_COMPLETED,
                lead_id=task.lead_id,
                manager_telegram_id=manager_id,
                payload={"task_id": task.id},
            )
            await session.commit()
            return task

    async def cancel_task(self, task_id: int, manager_id: int) -> ContactTask:
        async with self.session_factory() as session:
            task = await session.get(ContactTask, task_id)
            if task is None:
                raise LeadWorkflowError("Задача не найдена")
            if task.manager_telegram_id not in (None, manager_id):
                raise LeadAlreadyAssignedError(task.manager_telegram_id)
            if task.status == TaskStatus.CANCELLED:
                return task
            if task.status == TaskStatus.DONE:
                raise LeadWorkflowError("Выполненную задачу нельзя отменить")
            task.status = TaskStatus.CANCELLED
            if task.lead_id:
                lead = await session.get(Lead, task.lead_id)
                if lead is not None and lead.next_action_at == task.due_at:
                    lead.next_action_at = None
                    lead.next_action_note = None
            await ContactEventRepository(session).add(
                task.contact_id,
                ContactEventType.NEXT_CONTACT_CANCELLED,
                lead_id=task.lead_id,
                manager_telegram_id=manager_id,
                payload={"task_id": task.id},
            )
            await session.commit()
            return task

    async def reopen_not_lead(self, lead_id: int, manager_id: int) -> Lead:
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise LeadWorkflowError("Лид не найден")
            if lead.status != LeadStatus.NOT_LEAD:
                raise LeadWorkflowError("Вернуть в работу можно только лид, отмеченный как «не лид»")
            lead.status = LeadStatus.TAKEN
            lead.assigned_manager_telegram_id = manager_id
            contact = await session.get(Contact, lead.contact_id)
            if contact is not None:
                contact.assigned_manager_telegram_id = manager_id
            feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead.id))
            if feedback is not None:
                feedback.manager_is_lead = True
            await ContactEventRepository(session).add(
                lead.contact_id,
                ContactEventType.LEAD_REOPENED,
                lead_id=lead.id,
                manager_telegram_id=manager_id,
            )
            await session.commit()
            return lead

    async def upsert_deal(
        self,
        lead_id: int,
        manager_id: int,
        *,
        product_name: str = "",
        quantity: int | None = None,
        amount: Decimal | None = None,
    ) -> Deal:
        if quantity is not None and quantity <= 0:
            raise LeadWorkflowError("Количество должно быть больше нуля")
        if amount is not None and amount < 0:
            raise LeadWorkflowError("Сумма сделки не может быть отрицательной")
        async with self.session_factory() as session:
            lead = await session.get(Lead, lead_id)
            if lead is None:
                raise LeadWorkflowError("Лид не найден")
            if lead.assigned_manager_telegram_id not in (None, manager_id):
                raise LeadAlreadyAssignedError(lead.assigned_manager_telegram_id)
            deal = await session.scalar(select(Deal).where(Deal.lead_id == lead.id))
            created = deal is None
            if deal is None:
                deal = Deal(
                    contact_id=lead.contact_id,
                    lead_id=lead.id,
                    manager_telegram_id=manager_id,
                    status=DealStatus.NEW,
                    product_category=lead.product_category,
                )
                session.add(deal)
                await session.flush()
            elif deal.status in {DealStatus.WON, DealStatus.LOST}:
                raise LeadWorkflowError("Закрытую сделку нельзя изменять")
            if product_name.strip():
                deal.product_name = product_name.strip()
            if quantity is not None:
                deal.quantity = quantity
            if amount is not None:
                deal.amount = amount
                deal.final_amount = amount
            feedback = await session.scalar(select(AIFeedback).where(AIFeedback.lead_id == lead.id))
            if feedback is not None:
                feedback.deal_created = True
            if created:
                await ContactEventRepository(session).add(
                    lead.contact_id,
                    ContactEventType.DEAL_CREATED,
                    lead_id=lead.id,
                    deal_id=deal.id,
                    manager_telegram_id=manager_id,
                )
            await session.commit()
            return deal

    async def add_competitor(
        self,
        handle: str,
        *,
        display_name: str = "",
        category: str = "DIRECT",
        tier: str = "A",
        notes: str = "",
        vertical: str = "FURNITURE",
    ) -> Competitor:
        normalized = normalize_instagram_handle(handle)
        if not normalized:
            raise LeadWorkflowError("Укажите Instagram username конкурента")
        tier = tier.upper()
        if tier not in {"A", "B", "C"}:
            raise LeadWorkflowError("Приоритет должен быть A, B или C")
        interval = {"A": 180, "B": 600, "C": 1800}[tier]
        normalized_vertical = vertical.strip().upper()
        try:
            enrolled_vertical = Vertical(normalized_vertical)
        except ValueError as exc:
            raise LeadWorkflowError(
                "Вертикаль должна быть FURNITURE или ARTIFICIAL_RATTAN"
            ) from exc
        if enrolled_vertical not in {Vertical.FURNITURE, Vertical.ARTIFICIAL_RATTAN}:
            raise LeadWorkflowError(
                "Вертикаль должна быть FURNITURE или ARTIFICIAL_RATTAN"
            )
        async with self.session_factory() as session:
            competitor = await session.scalar(
                select(Competitor).where(Competitor.normalized_handle == normalized)
            )
            if competitor is None:
                competitor = Competitor(
                    handle=normalized,
                    normalized_handle=normalized,
                    display_name=display_name.strip() or normalized,
                    category=category.upper(),
                    tier=tier,
                    poll_interval_seconds=interval,
                    notes=notes.strip() or None,
                    active=True,
                    vertical=enrolled_vertical,
                )
                session.add(competitor)
            else:
                competitor.display_name = display_name.strip() or competitor.display_name
                competitor.category = category.upper()
                competitor.tier = tier
                competitor.poll_interval_seconds = interval
                competitor.notes = notes.strip() or competitor.notes
                competitor.vertical = enrolled_vertical
            await session.flush()
            if competitor.business_id:
                business = await session.get(BusinessEntity, competitor.business_id)
                sync_business_vertical_enrollment(business, vertical=enrolled_vertical)
            await session.commit()
            return competitor

    async def update_competitor(
        self,
        competitor_id: int,
        *,
        active: bool | None = None,
        tier: str | None = None,
        category: str | None = None,
        notification_policy: str | None = None,
        vertical: str | None = None,
    ) -> Competitor:
        async with self.session_factory() as session:
            competitor = await session.get(Competitor, competitor_id)
            if competitor is None:
                raise LeadWorkflowError("Конкурент не найден")
            if active is not None:
                competitor.active = active
            if tier is not None:
                normalized_tier = tier.upper()
                if normalized_tier not in {"A", "B", "C"}:
                    raise LeadWorkflowError("Приоритет должен быть A, B или C")
                competitor.tier = normalized_tier
                competitor.poll_interval_seconds = {"A": 180, "B": 600, "C": 1800}[normalized_tier]
            if category is not None:
                competitor.category = category.upper()
            if vertical is not None:
                normalized_vertical = vertical.strip().upper()
                try:
                    enrolled_vertical = Vertical(normalized_vertical)
                except ValueError as exc:
                    raise LeadWorkflowError(
                        "Вертикаль должна быть FURNITURE или ARTIFICIAL_RATTAN"
                    ) from exc
                if enrolled_vertical not in {Vertical.FURNITURE, Vertical.ARTIFICIAL_RATTAN}:
                    raise LeadWorkflowError(
                        "Вертикаль должна быть FURNITURE или ARTIFICIAL_RATTAN"
                    )
                competitor.vertical = enrolled_vertical
                if competitor.business_id:
                    business = await session.get(BusinessEntity, competitor.business_id)
                    sync_business_vertical_enrollment(
                        business, vertical=enrolled_vertical
                    )
            if notification_policy is not None:
                normalized_policy = notification_policy.strip().upper()
                if normalized_policy == "INHERIT":
                    competitor.notification_policy = None
                else:
                    try:
                        competitor.notification_policy = NotificationPolicy(normalized_policy)
                    except ValueError as exc:
                        raise LeadWorkflowError("Неизвестный режим уведомлений") from exc
            await session.commit()
            return competitor

    async def bulk_set_competitors_active(
        self,
        competitor_ids: list[int],
        *,
        active: bool,
    ) -> int:
        """Массово включить/поставить на паузу. Возвращает число обновлённых."""
        if not competitor_ids:
            return 0
        unique_ids = list(dict.fromkeys(int(item) for item in competitor_ids[:200]))
        async with self.session_factory() as session:
            result = await session.execute(
                select(Competitor).where(Competitor.id.in_(unique_ids))
            )
            rows = list(result.scalars().all())
            changed = 0
            for competitor in rows:
                if competitor.active != active:
                    competitor.active = active
                    changed += 1
            await session.commit()
            return changed


def _clean_optional(value: str | None, max_length: int) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise LeadWorkflowError(f"Поле слишком длинное: максимум {max_length} символов")
    return cleaned
