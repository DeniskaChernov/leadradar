from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Comment,
    Competitor,
    Contact,
    Lead,
    LeadStatus,
    NotificationLog,
    NotificationPolicy,
    NotificationStatus,
    Post,
    SignificantChange,
    SignificantChangeNotification,
)
from app.services.lead_workflow_service import LeadCard, LeadWorkflowService

logger = logging.getLogger(__name__)


class TelegramLeadNotifier:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        workflow: LeadWorkflowService,
        admin_chat_ids: list[int],
        *,
        hot_threshold: int,
        max_attempts: int = 3,
        notification_policy: NotificationPolicy = NotificationPolicy.ALL_NEW_COMMENTS,
        delivery_enabled: bool = True,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.workflow = workflow
        self.admin_chat_ids = admin_chat_ids
        self.hot_threshold = hot_threshold
        self.max_attempts = max_attempts
        self.notification_policy = notification_policy
        self.delivery_enabled = delivery_enabled
        self._delivery_lock = asyncio.Lock()

    async def notify_new_signal(self, lead_id: int) -> int:
        if not self.delivery_enabled:
            return 0
        if await self._effective_policy(lead_id) != NotificationPolicy.ALL_NEW_COMMENTS:
            return 0
        async with self._delivery_lock:
            return await self._queue_and_deliver(lead_id)

    async def notify_analyzed_lead(self, lead_id: int) -> int:
        if not self.delivery_enabled:
            return 0
        policy = await self._effective_policy(lead_id)
        card = await self.workflow.get_lead_card(lead_id)
        if policy == NotificationPolicy.ALL_NEW_COMMENTS:
            await self.refresh_lead_messages(lead_id)
            return 0
        is_commercial = card.status != LeadStatus.NOT_LEAD
        is_hot = is_commercial and card.score >= self.hot_threshold
        if policy == NotificationPolicy.COMMERCIAL_ONLY and is_commercial:
            async with self._delivery_lock:
                return await self._queue_and_deliver(lead_id)
        if policy == NotificationPolicy.HOT_ONLY and is_hot:
            async with self._delivery_lock:
                return await self._queue_and_deliver(lead_id)
        return 0

    async def notify_hot_lead(self, lead_id: int) -> int:
        if not self.delivery_enabled:
            return 0
        async with self._delivery_lock:
            return await self._notify_hot_lead(lead_id)

    async def notify_significant_change(self, change_id: int) -> int:
        if not self.delivery_enabled:
            return 0
        async with self._delivery_lock:
            targets = await self._change_target_chat_ids(change_id)
            for chat_id in targets:
                await self._ensure_change_log(change_id, chat_id)
            return await self._deliver_pending_changes(change_id=change_id)

    async def _notify_hot_lead(self, lead_id: int) -> int:
        return await self._queue_and_deliver(lead_id)

    async def _queue_and_deliver(self, lead_id: int) -> int:
        targets = await self._target_chat_ids(lead_id)
        if not targets:
            logger.warning("hot_lead_not_sent lead_id=%s reason=no_manager_chat_ids", lead_id)
            return 0
        for chat_id in targets:
            await self._ensure_log(lead_id, chat_id)
        return await self._deliver_pending(lead_id=lead_id)

    async def flush_pending(self) -> int:
        if not self.delivery_enabled:
            return 0
        async with self._delivery_lock:
            return await self._flush_pending()

    async def _effective_policy(self, lead_id: int) -> NotificationPolicy:
        async with self.session_factory() as session:
            configured = await session.scalar(
                select(Competitor.notification_policy)
                .join(Lead, Lead.competitor_id == Competitor.id)
                .where(Lead.id == lead_id)
            )
        return configured or self.notification_policy

    async def _flush_pending(self) -> int:
        await self._reconcile_hot_leads()
        return await self._deliver_pending() + await self._deliver_pending_changes()

    async def _target_chat_ids(self, lead_id: int) -> list[int]:
        async with self.session_factory() as session:
            manager_id = await session.scalar(
                select(Lead.assigned_manager_telegram_id).where(Lead.id == lead_id)
            )
        if manager_id:
            return [int(manager_id)]
        return list(dict.fromkeys(self.admin_chat_ids))

    async def _change_target_chat_ids(self, change_id: int) -> list[int]:
        async with self.session_factory() as session:
            manager_id = await session.scalar(
                select(Lead.assigned_manager_telegram_id)
                .join(SignificantChange, SignificantChange.lead_id == Lead.id)
                .where(SignificantChange.id == change_id)
            )
        if manager_id:
            return [int(manager_id)]
        return list(dict.fromkeys(self.admin_chat_ids))

    async def refresh_lead_messages(self, lead_id: int) -> None:
        card = await self.workflow.get_lead_card(lead_id)
        async with self.session_factory() as session:
            logs = (
                await session.scalars(
                    select(NotificationLog).where(
                        NotificationLog.lead_id == lead_id,
                        NotificationLog.status == NotificationStatus.SENT,
                        NotificationLog.message_id.is_not(None),
                        NotificationLog.content_version < 2,
                    )
                )
            ).all()
        for item in logs:
            try:
                await self.bot.edit_message_text(
                    chat_id=item.chat_id,
                    message_id=item.message_id,
                    text=render_lead_card(card),
                    reply_markup=lead_keyboard(card),
                )
                async with self.session_factory() as session:
                    log = await session.get(NotificationLog, item.id)
                    if log is not None and log.content_version < 2:
                        log.content_version = 2
                        log.error = None
                        await session.commit()
            except Exception as exc:
                logger.warning(
                    "telegram_message_refresh_failed lead_id=%s chat_id=%s error_type=%s",
                    lead_id,
                    item.chat_id,
                    type(exc).__name__,
                )
                await self._send_enrichment_fallback(item.id, card, exc)

    async def _send_enrichment_fallback(
        self, log_id: int, card: LeadCard, edit_error: Exception
    ) -> None:
        async with self.session_factory() as session:
            log = await session.get(NotificationLog, log_id)
            if (
                log is None
                or log.enrichment_followup_sent_at is not None
                or log.content_version >= 2
            ):
                return
            chat_id = log.chat_id
        try:
            await self.bot.send_message(
                chat_id,
                render_enrichment_followup(card),
                reply_markup=lead_keyboard(card),
            )
        except Exception as fallback_error:
            logger.error(
                "telegram_enrichment_fallback_failed lead_id=%s chat_id=%s error_type=%s",
                card.lead_id,
                chat_id,
                type(fallback_error).__name__,
            )
            return
        async with self.session_factory() as session:
            log = await session.get(NotificationLog, log_id)
            if log is not None and log.content_version < 2:
                log.content_version = 2
                log.enrichment_followup_sent_at = datetime.now(UTC)
                log.error = f"edit failed: {type(edit_error).__name__}"
                await session.commit()

    async def _reconcile_hot_leads(self) -> None:
        async with self.session_factory() as session:
            leads = (
                await session.execute(
                    select(Lead.id, Lead.assigned_manager_telegram_id)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .where(
                        Lead.lead_score >= self.hot_threshold,
                        Lead.status.in_([LeadStatus.NEW, LeadStatus.TAKEN]),
                        Comment.is_baseline.is_(False),
                    )
                )
            ).all()
        for lead_id, manager_id in leads:
            targets = [int(manager_id)] if manager_id else self.admin_chat_ids
            for chat_id in dict.fromkeys(targets):
                await self._ensure_log(lead_id, chat_id)

    async def _ensure_log(self, lead_id: int, chat_id: int) -> None:
        async with self.session_factory() as session:
            exists = await session.scalar(
                select(NotificationLog.id).where(
                    NotificationLog.lead_id == lead_id,
                    NotificationLog.chat_id == chat_id,
                )
            )
            if exists is not None:
                return
            session.add(NotificationLog(lead_id=lead_id, chat_id=chat_id))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

    async def _ensure_change_log(self, change_id: int, chat_id: int) -> None:
        async with self.session_factory() as session:
            exists = await session.scalar(
                select(SignificantChangeNotification.id).where(
                    SignificantChangeNotification.change_id == change_id,
                    SignificantChangeNotification.chat_id == chat_id,
                )
            )
            if exists is not None:
                return
            session.add(
                SignificantChangeNotification(change_id=change_id, chat_id=chat_id)
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()

    async def _deliver_pending(self, *, lead_id: int | None = None) -> int:
        now = datetime.now(UTC)
        retry_due = and_(
            NotificationLog.status == NotificationStatus.FAILED,
            NotificationLog.next_attempt_at.is_not(None),
            NotificationLog.next_attempt_at <= now,
        )
        async with self.session_factory() as session:
            query = select(NotificationLog.id).where(
                or_(NotificationLog.status == NotificationStatus.PENDING, retry_due),
                NotificationLog.attempt_count < self.max_attempts,
            )
            if lead_id is not None:
                query = query.where(NotificationLog.lead_id == lead_id)
            log_ids = (await session.scalars(query.order_by(NotificationLog.id))).all()
        sent = 0
        for log_id in log_ids:
            sent += int(await self._claim_and_send(log_id))
        return sent

    async def _claim_and_send(self, log_id: int) -> bool:
        now = datetime.now(UTC)
        retry_due = and_(
            NotificationLog.status == NotificationStatus.FAILED,
            NotificationLog.next_attempt_at.is_not(None),
            NotificationLog.next_attempt_at <= now,
        )
        async with self.session_factory() as session:
            claimed = (
                await session.execute(
                    update(NotificationLog)
                    .where(
                        NotificationLog.id == log_id,
                        or_(
                            NotificationLog.status == NotificationStatus.PENDING,
                            retry_due,
                        ),
                        NotificationLog.attempt_count < self.max_attempts,
                    )
                    .values(
                        status=NotificationStatus.PROCESSING,
                        attempt_count=NotificationLog.attempt_count + 1,
                        last_attempt_at=now,
                        next_attempt_at=None,
                        error=None,
                    )
                    .returning(
                        NotificationLog.lead_id,
                        NotificationLog.chat_id,
                        NotificationLog.attempt_count,
                    )
                )
            ).one_or_none()
            await session.commit()
        if claimed is None:
            return False
        lead_id, chat_id, attempt_count = claimed
        try:
            card = await self.workflow.get_lead_card(lead_id)
            initial = card.status in {LeadStatus.ANALYZING, LeadStatus.AI_PENDING}
            message = await self.bot.send_message(
                chat_id,
                render_signal_card(card) if initial else render_lead_card(card),
                reply_markup=lead_keyboard(card),
            )
            async with self.session_factory() as session:
                log = await session.get(NotificationLog, log_id)
                if log is not None and log.status == NotificationStatus.PROCESSING:
                    log.status = NotificationStatus.SENT
                    log.message_id = message.message_id
                    log.content_version = 1 if initial else 2
                    await session.commit()
            return True
        except Exception as exc:
            next_attempt = None
            if attempt_count < self.max_attempts:
                next_attempt = datetime.now(UTC) + timedelta(
                    seconds=min(300, 10 * (2 ** (attempt_count - 1)))
                )
            async with self.session_factory() as session:
                log = await session.get(NotificationLog, log_id)
                if log is not None and log.status == NotificationStatus.PROCESSING:
                    log.status = NotificationStatus.FAILED
                    log.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                    log.next_attempt_at = next_attempt
                    await session.commit()
            logger.error(
                "telegram_notification_failed lead_id=%s chat_id=%s attempt=%s error_type=%s",
                lead_id,
                chat_id,
                attempt_count,
                type(exc).__name__,
            )
            return False

    async def _deliver_pending_changes(self, *, change_id: int | None = None) -> int:
        now = datetime.now(UTC)
        retry_due = and_(
            SignificantChangeNotification.status == NotificationStatus.FAILED,
            SignificantChangeNotification.next_attempt_at.is_not(None),
            SignificantChangeNotification.next_attempt_at <= now,
        )
        async with self.session_factory() as session:
            query = select(SignificantChangeNotification.id).where(
                or_(
                    SignificantChangeNotification.status == NotificationStatus.PENDING,
                    retry_due,
                ),
                SignificantChangeNotification.attempt_count < self.max_attempts,
            )
            if change_id is not None:
                query = query.where(SignificantChangeNotification.change_id == change_id)
            log_ids = list(await session.scalars(query.order_by(SignificantChangeNotification.id)))
        sent = 0
        for log_id in log_ids:
            sent += int(await self._claim_and_send_change(log_id))
        return sent

    async def _claim_and_send_change(self, log_id: int) -> bool:
        now = datetime.now(UTC)
        retry_due = and_(
            SignificantChangeNotification.status == NotificationStatus.FAILED,
            SignificantChangeNotification.next_attempt_at.is_not(None),
            SignificantChangeNotification.next_attempt_at <= now,
        )
        async with self.session_factory() as session:
            claimed = (
                await session.execute(
                    update(SignificantChangeNotification)
                    .where(
                        SignificantChangeNotification.id == log_id,
                        or_(
                            SignificantChangeNotification.status == NotificationStatus.PENDING,
                            retry_due,
                        ),
                        SignificantChangeNotification.attempt_count < self.max_attempts,
                    )
                    .values(
                        status=NotificationStatus.PROCESSING,
                        attempt_count=SignificantChangeNotification.attempt_count + 1,
                        last_attempt_at=now,
                        next_attempt_at=None,
                        error=None,
                    )
                    .returning(
                        SignificantChangeNotification.change_id,
                        SignificantChangeNotification.chat_id,
                        SignificantChangeNotification.attempt_count,
                    )
                )
            ).one_or_none()
            await session.commit()
        if claimed is None:
            return False
        change_id, chat_id, attempt_count = claimed
        try:
            async with self.session_factory() as session:
                row = (
                    await session.execute(
                        select(SignificantChange, Contact, Lead, Comment, Post)
                        .join(Contact, Contact.id == SignificantChange.contact_id)
                        .join(Lead, Lead.id == SignificantChange.lead_id)
                        .join(Comment, Comment.id == Lead.comment_id)
                        .join(Post, Post.id == Comment.post_id)
                        .where(SignificantChange.id == change_id)
                    )
                ).one()
            change, contact, lead, _comment, post = row
            message = await self.bot.send_message(
                chat_id,
                render_significant_change(change, contact),
                reply_markup=significant_change_keyboard(contact, lead, post),
            )
            async with self.session_factory() as session:
                log = await session.get(SignificantChangeNotification, log_id)
                if log is not None and log.status == NotificationStatus.PROCESSING:
                    log.status = NotificationStatus.SENT
                    log.message_id = message.message_id
                    await session.commit()
            return True
        except Exception as exc:
            next_attempt = None
            if attempt_count < self.max_attempts:
                next_attempt = datetime.now(UTC) + timedelta(
                    seconds=min(300, 10 * (2 ** (attempt_count - 1)))
                )
            async with self.session_factory() as session:
                log = await session.get(SignificantChangeNotification, log_id)
                if log is not None and log.status == NotificationStatus.PROCESSING:
                    log.status = NotificationStatus.FAILED
                    log.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                    log.next_attempt_at = next_attempt
                    await session.commit()
            logger.error(
                "telegram_change_notification_failed change_id=%s chat_id=%s attempt=%s error_type=%s",
                change_id,
                chat_id,
                attempt_count,
                type(exc).__name__,
            )
            return False
def render_lead_card(card: LeadCard) -> str:
    if card.status == LeadStatus.NOT_LEAD:
        heat = "✅ Сигнал проверен · не лид"
    elif card.score >= 85 or card.recent_signal_count >= 2:
        heat = "🔥 Горячий лид"
    else:
        heat = "📌 Коммерческий сигнал"
    manager = (
        f"\n\n👨‍💼 Менеджер: <code>{card.assigned_manager_telegram_id}</code>"
        if card.assigned_manager_telegram_id
        else ""
    )
    history = f"{card.previous_signal_count} предыдущих сигналов"
    if card.recent_signal_count:
        history += f" · {card.recent_signal_count + 1} за последние 14 дней"
    return (
        f"{heat} · <b>{card.score}/100</b>\n\n"
        f"👤 {escape(card.display_name or card.username)}\n"
        f"@{escape(card.username)}\n\n"
        f"💬 <b>Комментарий:</b>\n{escape(card.comment)}\n\n"
        f"🏢 <b>Компания:</b> {escape(card.competitor.upper())}\n\n"
        f"🎯 <b>Intent:</b> {escape(card.intent)}\n"
        f"🪑 <b>Интерес:</b> {escape(card.product_category or 'не определён')}\n\n"
        f"📹 <b>Reel:</b>\n{escape(card.post_caption[:350])}\n\n"
        f"🧠 <b>Почему HOT:</b>\n{escape(card.ai_reason)}\n\n"
        f"📚 <b>История:</b> {history}\n"
        f"📌 <b>Статус:</b> {card.status.value}"
        f"{manager}"
    )


def render_signal_card(card: LeadCard) -> str:
    return (
        "🔔 <b>Новый сигнал</b>\n\n"
        f"@{escape(card.username)}\n"
        f"\"{escape(card.comment)}\"\n\n"
        f"Источник: {escape(card.competitor.upper())}\n"
        "Товар: определяется…\n\n"
        "⏳ Анализируем интерес клиента"
    )


def render_enrichment_followup(card: LeadCard) -> str:
    return (
        f"🧠 <b>Анализ сигнала завершён · {card.score}/100</b>\n"
        f"@{escape(card.username)} · {escape(card.intent)}\n"
        f"Интерес: {escape(card.product_category or 'не определён')}\n"
        f"{escape(card.ai_reason[:500])}"
    )


def render_significant_change(change: SignificantChange, contact: Contact) -> str:
    severity_label = {
        "CRITICAL": "критическое",
        "HIGH": "важное",
        "MEDIUM": "заметное",
    }.get(change.severity, "заметное")
    return (
        "🚨 <b>Лид стал горячее</b>\n\n"
        f"@{escape(contact.username)}\n\n"
        f"{escape(change.summary)}\n\n"
        f"Приоритет: <b>{change.previous_priority} → {change.current_priority}</b>\n"
        f"Уровень изменения: {severity_label}"
    )


def significant_change_keyboard(
    contact: Contact, lead: Lead, post: Post
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👤 Instagram", url=contact.profile_url),
                InlineKeyboardButton(text="📹 Источник", url=post.url),
            ],
            [
                InlineKeyboardButton(
                    text="🔥 Взять в работу", callback_data=f"lead:take:{lead.id}"
                )
            ],
        ]
    )


def lead_keyboard(card: LeadCard) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="👤 Профиль", url=card.profile_url),
            InlineKeyboardButton(text="📹 Reel", url=card.post_url),
        ]
    ]
    if card.status in {LeadStatus.ANALYZING, LeadStatus.AI_PENDING, LeadStatus.NEW}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔥 Взять лид", callback_data=f"lead:take:{card.lead_id}"
                ),
                InlineKeyboardButton(
                    text="🚫 Не лид", callback_data=f"lead:not:{card.lead_id}"
                ),
            ]
        )
    elif card.status.value == "TAKEN":
        rows.append(
            [
                InlineKeyboardButton(
                    text="💰 Создать сделку", callback_data=f"deal:create:{card.lead_id}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
