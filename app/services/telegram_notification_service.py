from __future__ import annotations

import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import NotificationLog, NotificationStatus
from app.services.lead_workflow_service import LeadCard, LeadWorkflowService

logger = logging.getLogger(__name__)


class TelegramLeadNotifier:
    def __init__(
        self,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        workflow: LeadWorkflowService,
        admin_chat_ids: list[int],
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.workflow = workflow
        self.admin_chat_ids = admin_chat_ids

    async def notify_hot_lead(self, lead_id: int) -> None:
        if not self.admin_chat_ids:
            logger.warning("hot_lead_not_sent lead_id=%s reason=no_admin_chat_ids", lead_id)
            return
        card = await self.workflow.get_lead_card(lead_id)
        for chat_id in self.admin_chat_ids:
            await self._send_one(card, chat_id)

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

    async def _send_one(self, card: LeadCard, chat_id: int) -> None:
        async with self.session_factory() as session:
            log = await session.scalar(
                select(NotificationLog).where(
                    NotificationLog.lead_id == card.lead_id,
                    NotificationLog.chat_id == chat_id,
                )
            )
            if log is not None and log.status == NotificationStatus.SENT:
                return
            if log is None:
                log = NotificationLog(lead_id=card.lead_id, chat_id=chat_id)
                session.add(log)
            log.status = NotificationStatus.PENDING
            log.error = None
            await session.commit()
            log_id = log.id
        try:
            message = await self.bot.send_message(
                chat_id,
                render_lead_card(card),
                reply_markup=lead_keyboard(card),
            )
            async with self.session_factory() as session:
                log = await session.get(NotificationLog, log_id)
                if log is not None:
                    log.status = NotificationStatus.SENT
                    log.message_id = message.message_id
                    await session.commit()
        except TelegramAPIError as exc:
            async with self.session_factory() as session:
                log = await session.get(NotificationLog, log_id)
                if log is not None:
                    log.status = NotificationStatus.FAILED
                    log.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                    await session.commit()
            logger.error(
                "telegram_notification_failed lead_id=%s chat_id=%s error_type=%s",
                card.lead_id,
                chat_id,
                type(exc).__name__,
            )


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

