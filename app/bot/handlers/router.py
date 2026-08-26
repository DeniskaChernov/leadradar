from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from app.bot.states import DealLostForm, DealWonForm
from app.config import Settings
from app.services.lead_workflow_service import (
    LeadAlreadyAssignedError,
    LeadWorkflowError,
    LeadWorkflowService,
)
from app.services.monitor_controller import MonitorController
from app.services.telegram_notification_service import (
    TelegramLeadNotifier,
    lead_keyboard,
    render_lead_card,
)

LOST_REASONS = {
    "expensive": "дорого",
    "product": "нет нужного товара",
    "color": "нет нужного цвета",
    "stock": "нет в наличии",
    "waiting": "долго ждать",
    "silent": "не отвечает",
    "competitor": "купил у конкурента",
    "postponed": "отложил покупку",
}


def build_router(
    settings: Settings,
    workflow: LeadWorkflowService,
    notifier: TelegramLeadNotifier,
    controller: MonitorController,
) -> Router:
    router = Router(name="lead-radar")

    def authorized(event: Message | CallbackQuery) -> bool:
        if event.from_user is None:
            return False
        if isinstance(event, Message):
            chat_id = event.chat.id
        elif event.message is not None:
            chat_id = event.message.chat.id
        else:
            chat_id = None
        return event.from_user.id in settings.telegram_admin_chat_ids or (
            chat_id in settings.telegram_admin_chat_ids
        )

    async def reject(event: Message | CallbackQuery) -> None:
        text = "Нет доступа. Добавьте этот ID в TELEGRAM_ADMIN_CHAT_IDS."
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        else:
            await event.answer(text)

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else "unknown"
        has_access = authorized(message)
        access_text = (
            "✅ Доступ подтверждён.\n"
            if has_access
            else "⛔ Доступ пока не настроен.\n"
        )
        next_step = (
            "Используйте кнопки меню или команду /help."
            if has_access
            else "Добавьте нужный ID в TELEGRAM_ADMIN_CHAT_IDS и перезапустите бота."
        )
        await message.answer(
            f"📡 <b>Lead Radar</b>\n\n{access_text}"
            f"Chat ID: <code>{message.chat.id}</code>\n"
            f"User ID: <code>{user_id}</code>\n\n{next_step}",
            reply_markup=main_menu() if has_access else None,
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        await message.answer(
            "ℹ️ <b>Как пользоваться Lead Radar</b>\n\n"
            "/status — работает ли мониторинг\n"
            "/stats — контакты, лиды и сделки\n"
            "/hot — карточки открытых HOT-лидов\n"
            "/lead 12 — открыть лид №12\n"
            "/scan — проверить Instagram сейчас\n"
            "/competitors — кого отслеживаем\n"
            "/cancel — отменить заполнение сделки\n\n"
            "Новые комментарии сохраняются автоматически. База данных — источник истины.",
            reply_markup=main_menu(),
        )

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        snapshot = controller.snapshot()
        cycle = (
            f"идёт сейчас ({snapshot.cycle_trigger})"
            if snapshot.cycle_running
            else "ожидает следующего запуска"
        )
        last_cycle = _format_datetime(snapshot.last_cycle_completed_at)
        last_result = "ещё нет"
        if snapshot.last_stats is not None:
            last_result = (
                f"новых комментариев: {snapshot.last_stats.comments_created}, "
                f"лидов: {snapshot.last_stats.leads_created}, "
                f"ошибок: {snapshot.last_stats.errors}"
            )
        await message.answer(
            "✅ Lead Radar работает\n"
            f"Мониторинг: <b>{cycle}</b>\n"
            f"Запущен: <b>{_format_duration(datetime.now(UTC) - snapshot.started_at)}</b> назад\n"
            f"Циклов завершено: <b>{snapshot.cycles_completed}</b>\n"
            f"Последний цикл: <b>{last_cycle}</b>\n"
            f"Результат: <b>{last_result}</b>\n"
            f"Последняя системная ошибка: <b>{escape(snapshot.last_error or 'нет')}</b>\n\n"
            f"Provider: <b>{settings.instagram_provider}</b>\n"
            f"Конкурентов: <b>{len(settings.competitors)}</b>\n"
            f"HOT-порог: <b>{settings.hot_lead_threshold}</b>"
        )

    @router.message(Command("scan"))
    async def scan(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        if not controller.start_cycle("manual"):
            return await message.answer("⏳ Проверка уже выполняется. Посмотрите /status.")
        await message.answer("🔎 Проверка Instagram запущена. Я сообщу результат здесь.")
        task = asyncio.create_task(_report_scan_result(message, controller))
        task.add_done_callback(_consume_task_exception)

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        value = await workflow.get_stats()
        await message.answer(
            "📊 <b>Статистика</b>\n\n"
            f"Контакты: {value.contacts}\n"
            f"Комментарии: {value.comments}\n"
            f"HOT-лиды: {value.hot_leads}\n"
            f"Открытые лиды: {value.open_leads}\n"
            f"Продажи: {value.won_deals}\n"
            f"Проиграны: {value.lost_deals}\n"
            f"Ожидают AI: {value.ai_pending}\n"
            f"Уведомления в очереди: {value.notification_backlog}"
        )

    @router.message(Command("hot"))
    async def hot(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        cards = await workflow.list_hot_leads()
        if not cards:
            return await message.answer("Сейчас нет открытых HOT-лидов.")
        await message.answer(f"🔥 Открытых HOT-лидов: <b>{len(cards)}</b>")
        for card in cards:
            await message.answer(render_lead_card(card), reply_markup=lead_keyboard(card))

    @router.message(Command("lead"))
    async def lead(message: Message, command: CommandObject) -> None:
        if not authorized(message):
            return await reject(message)
        try:
            lead_id = int(command.args or "")
            card = await workflow.get_lead_card(lead_id)
        except ValueError:
            return await message.answer("Укажите ID: <code>/lead 12</code>")
        except LeadWorkflowError:
            return await message.answer("Лид с таким ID не найден.")
        await message.answer(render_lead_card(card), reply_markup=lead_keyboard(card))

    @router.message(Command("competitors"))
    async def competitors(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        await message.answer(
            "🏢 Конкуренты:\n" + "\n".join(escape(item) for item in settings.competitors)
        )

    @router.message(Command("cancel"))
    async def cancel(message: Message, state: FSMContext) -> None:
        if not authorized(message):
            return await reject(message)
        current = await state.get_state()
        await state.clear()
        text = "Диалог отменён." if current else "Сейчас нет активного диалога."
        await message.answer(f"↩️ {text}", reply_markup=main_menu())

    @router.callback_query(F.data.startswith("lead:take:"))
    async def take_lead(callback: CallbackQuery) -> None:
        if not authorized(callback):
            return await reject(callback)
        lead_id = _callback_id(callback)
        try:
            await workflow.assign_manager(lead_id, callback.from_user.id)
            await notifier.refresh_lead_messages(lead_id)
            await _refresh_visible_card(callback, workflow)
            await callback.answer("Лид назначен вам")
        except LeadAlreadyAssignedError as exc:
            await callback.answer(f"Лид уже взял менеджер {exc.manager_id}", show_alert=True)
        except LeadWorkflowError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("lead:not:"))
    async def not_lead(callback: CallbackQuery) -> None:
        if not authorized(callback):
            return await reject(callback)
        lead_id = _callback_id(callback)
        try:
            await workflow.mark_not_lead(lead_id, callback.from_user.id)
            await notifier.refresh_lead_messages(lead_id)
            await _refresh_visible_card(callback, workflow)
            await callback.answer("Feedback сохранён")
        except LeadWorkflowError as exc:
            await callback.answer(str(exc), show_alert=True)

    @router.callback_query(F.data.startswith("deal:create:"))
    async def create_deal(callback: CallbackQuery) -> None:
        if not authorized(callback):
            return await reject(callback)
        try:
            deal = await workflow.create_deal(_callback_id(callback), callback.from_user.id)
        except LeadWorkflowError as exc:
            return await callback.answer(str(exc), show_alert=True)
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Продажа", callback_data=f"deal:won:{deal.id}"
                    ),
                    InlineKeyboardButton(
                        text="❌ Проиграна", callback_data=f"deal:lost:{deal.id}"
                    ),
                ]
            ]
        )
        if callback.message:
            await callback.message.answer(f"Сделка #{deal.id} создана.", reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(F.data.startswith("deal:won:"))
    async def won_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not authorized(callback):
            return await reject(callback)
        await state.set_state(DealWonForm.product)
        await state.update_data(deal_id=_callback_id(callback))
        if callback.message:
            await callback.message.answer("Введите название товара:")
        await callback.answer()

    @router.message(DealWonForm.product)
    async def won_product(message: Message, state: FSMContext) -> None:
        if not authorized(message):
            return await reject(message)
        await state.update_data(product_name=message.text or "")
        await state.set_state(DealWonForm.amount)
        await message.answer("Введите итоговую сумму цифрами:")

    @router.message(DealWonForm.amount)
    async def won_amount(message: Message, state: FSMContext) -> None:
        if not authorized(message):
            return await reject(message)
        try:
            amount = Decimal((message.text or "").replace(" ", "").replace(",", "."))
            if amount <= 0:
                raise InvalidOperation
        except InvalidOperation:
            return await message.answer("Нужна положительная сумма, например 4500000.")
        await state.update_data(amount=str(amount))
        await state.set_state(DealWonForm.quantity)
        await message.answer("Введите количество:")

    @router.message(DealWonForm.quantity)
    async def won_quantity(message: Message, state: FSMContext) -> None:
        if not authorized(message):
            return await reject(message)
        try:
            quantity = int(message.text or "")
            if quantity <= 0:
                raise ValueError
        except ValueError:
            return await message.answer("Нужно целое положительное количество.")
        data = await state.get_data()
        try:
            deal = await workflow.win_deal(
                int(data["deal_id"]),
                message.from_user.id,
                product_name=str(data["product_name"]),
                amount=Decimal(str(data["amount"])),
                quantity=quantity,
            )
        except LeadWorkflowError as exc:
            await state.clear()
            return await message.answer(f"Не удалось закрыть сделку: {exc}")
        await state.clear()
        await notifier.refresh_lead_messages(deal.lead_id or 0)
        await message.answer(f"✅ Сделка #{deal.id} отмечена как WON.")

    @router.callback_query(F.data.startswith("deal:lost:"))
    async def lost_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not authorized(callback):
            return await reject(callback)
        deal_id = _callback_id(callback)
        if callback.message:
            await callback.message.answer(
                "Почему сделка проиграна?",
                reply_markup=lost_reason_keyboard(deal_id),
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("deal:reason:"))
    async def lost_reason_selected(callback: CallbackQuery, state: FSMContext) -> None:
        if not authorized(callback):
            return await reject(callback)
        try:
            _, _, deal_id_text, code = (callback.data or "").split(":", maxsplit=3)
            deal_id = int(deal_id_text)
        except (TypeError, ValueError):
            return await callback.answer("Некорректная причина", show_alert=True)
        if code == "other":
            await state.set_state(DealLostForm.reason)
            await state.update_data(deal_id=deal_id)
            if callback.message:
                await callback.message.answer("Опишите причину одним сообщением:")
            return await callback.answer()
        reason = LOST_REASONS.get(code)
        if reason is None:
            return await callback.answer("Неизвестная причина", show_alert=True)
        try:
            deal = await workflow.lose_deal(
                deal_id, callback.from_user.id, reason=reason
            )
        except LeadWorkflowError as exc:
            return await callback.answer(str(exc), show_alert=True)
        await notifier.refresh_lead_messages(deal.lead_id or 0)
        if callback.message:
            await callback.message.edit_text(
                f"❌ Сделка #{deal.id} отмечена как LOST.\nПричина: {reason}"
            )
        await callback.answer("Результат сохранён")

    @router.message(DealLostForm.reason)
    async def lost_reason(message: Message, state: FSMContext) -> None:
        if not authorized(message):
            return await reject(message)
        reason = (message.text or "").strip()
        if not reason:
            return await message.answer("Причина не может быть пустой.")
        data = await state.get_data()
        try:
            deal = await workflow.lose_deal(
                int(data["deal_id"]), message.from_user.id, reason=reason
            )
        except LeadWorkflowError as exc:
            await state.clear()
            return await message.answer(f"Не удалось закрыть сделку: {exc}")
        await state.clear()
        await notifier.refresh_lead_messages(deal.lead_id or 0)
        await message.answer(f"❌ Сделка #{deal.id} отмечена как LOST.")

    @router.message()
    async def unknown_message(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        await message.answer(
            "Не понял сообщение. Выберите команду в меню или откройте /help.",
            reply_markup=main_menu(),
        )

    return router


def _callback_id(callback: CallbackQuery) -> int:
    if callback.data is None:
        raise LeadWorkflowError("Callback data is missing")
    try:
        return int(callback.data.rsplit(":", maxsplit=1)[1])
    except (IndexError, ValueError) as exc:
        raise LeadWorkflowError("Invalid callback data") from exc


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/status"), KeyboardButton(text="/stats")],
            [KeyboardButton(text="/hot"), KeyboardButton(text="/scan")],
            [KeyboardButton(text="/competitors"), KeyboardButton(text="/help")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите команду",
    )


def lost_reason_keyboard(deal_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=reason.capitalize(), callback_data=f"deal:reason:{deal_id}:{code}"
        )
        for code, reason in LOST_REASONS.items()
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append(
        [
            InlineKeyboardButton(
                text="Другая причина", callback_data=f"deal:reason:{deal_id}:other"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _report_scan_result(
    message: Message, controller: MonitorController
) -> None:
    try:
        stats = await controller.wait_current()
    except Exception:
        await message.answer("⚠️ Проверка завершилась системной ошибкой. Детали есть в /status.")
        return
    if stats is None:
        return
    await message.answer(
        "✅ <b>Проверка завершена</b>\n\n"
        f"Reels: {stats.reels_found}\n"
        f"Просмотрено комментариев: {stats.comments_seen}\n"
        f"Новых комментариев: {stats.comments_created}\n"
        f"Новых лидов: {stats.leads_created}\n"
        f"HOT-уведомлений: {stats.hot_notifications}\n"
        f"Ошибок: {stats.errors}"
    )


async def _refresh_visible_card(
    callback: CallbackQuery, workflow: LeadWorkflowService
) -> None:
    if callback.message is None:
        return
    card = await workflow.get_lead_card(_callback_id(callback))
    try:
        await callback.message.edit_text(
            render_lead_card(card), reply_markup=lead_keyboard(card)
        )
    except TelegramAPIError:
        pass


def _format_datetime(value: datetime | None) -> str:
    return "ещё не выполнялся" if value is None else value.strftime("%d.%m %H:%M UTC")


def _format_duration(value: timedelta) -> str:
    seconds = max(0, int(value.total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин {seconds} сек"
    return f"{seconds} сек"


def _consume_task_exception(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()
