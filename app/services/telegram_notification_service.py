from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Lead, LeadStatus, NotificationLog, NotificationStatus
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
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.workflow = workflow
        self.admin_chat_ids = admin_chat_ids
        self.hot_threshold = hot_threshold
        self.max_attempts = max_attempts
        self._delivery_lock = asyncio.Lock()

    async def notify_hot_lead(self, lead_id: int) -> int:
        async with self._delivery_lock:
            return await self._notify_hot_lead(lead_id)

    async def _notify_hot_lead(self, lead_id: int) -> int:
        if not self.admin_chat_ids:
            logger.warning("hot_lead_not_sent lead_id=%s reason=no_admin_chat_ids", lead_id)
            return 0
        for chat_id in self.admin_chat_ids:
            await self._ensure_log(lead_id, chat_id)
        return await self._deliver_pending(lead_id=lead_id)

    async def flush_pending(self) -> int:
        async with self._delivery_lock:
            return await self._flush_pending()

    async def _flush_pending(self) -> int:
        if not self.admin_chat_ids:
            return 0
        await self._reconcile_hot_leads()
        return await self._deliver_pending()

    async def refresh_lead_messages(self, lead_id: int) -> None:
        card = await self.workflow.get_lead_card(lead_id)
        async with self.session_factory() as session:
            logs = (
                await session.scalars(
                    select(NotificationLog).where(
                        NotificationLog.lead_id == lead_id,
                        NotificationLog.status == NotificationStatus.SENT,
                        NotificationLog.message_id.is_not(None),
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
            except TelegramAPIError as exc:
                logger.warning(
                    "telegram_message_refresh_failed lead_id=%s chat_id=%s error_type=%s",
                    lead_id,
                    item.chat_id,
                    type(exc).__name__,
                )

    async def _reconcile_hot_leads(self) -> None:
        async with self.session_factory() as session:
            lead_ids = (
                await session.scalars(
                    select(Lead.id).where(
                        Lead.lead_score >= self.hot_threshold,
                        Lead.status.in_([LeadStatus.NEW, LeadStatus.TAKEN]),
                    )
                )
            ).all()
        for lead_id in lead_ids:
            for chat_id in self.admin_chat_ids:
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
            message = await self.bot.send_message(
                chat_id,
                render_lead_card(card),
                reply_markup=lead_keyboard(card),
            )
            async with self.session_factory() as session:
                log = await session.get(NotificationLog, log_id)
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


def render_lead_card(card: LeadCard) -> str:
    heat = "🔥 SUPER HOT" if card.recent_signal_count >= 2 else "🔥 HOT LEAD"
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


def lead_keyboard(card: LeadCard) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="👤 Профиль", url=card.profile_url),
            InlineKeyboardButton(text="📹 Reel", url=card.post_url),
        ]
    ]
    if card.status.value == "NEW":
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
