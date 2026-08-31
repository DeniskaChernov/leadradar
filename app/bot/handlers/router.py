from __future__ import annotations

import asyncio
import contextlib
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
    WebAppInfo,
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


def _dashboard_url(settings: Settings) -> str:
    return settings.web_public_url or f"http://{settings.web_host}:{settings.web_port}"


def build_main_menu(settings: Settings) -> ReplyKeyboardMarkup:
    """Reply keyboard with optional Telegram WebApp button when HTTPS URL is configured."""
    dashboard_url = _dashboard_url(settings)
    third_row: list[KeyboardButton]
    if dashboard_url.startswith("https://"):
        third_row = [
            KeyboardButton(text="🌐 Кабина", web_app=WebAppInfo(url=dashboard_url)),
            KeyboardButton(text="/competitors"),
        ]
    else:
        third_row = [
            KeyboardButton(text="/competitors"),
            KeyboardButton(text="/web"),
        ]
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/status"), KeyboardButton(text="/stats")],
            [KeyboardButton(text="/hot"), KeyboardButton(text="/scan")],
            third_row,
            [KeyboardButton(text="/help")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Команда или 🌐 Кабина",
    )


def build_router(
    settings: Settings,
    workflow: LeadWorkflowService,
    notifier: TelegramLeadNotifier,
    controller: MonitorController,
) -> Router:
    router = Router(name="lead-radar")
    def main_menu() -> ReplyKeyboardMarkup:
        return build_main_menu(settings)

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
        dashboard_url = _dashboard_url(settings)
        next_step = (
            f"Основная работа теперь в веб-интерфейсе: {dashboard_url}\n"
            "Telegram оставляем для HOT-уведомлений и быстрых действий."
            if has_access
            else "Добавьте нужный ID в TELEGRAM_ADMIN_CHAT_IDS и перезапустите бота."
        )
        await message.answer(
            f"📡 <b>Lead Radar</b>\n\n{access_text}"
            f"Chat ID: <code>{message.chat.id}</code>\n"
            f"User ID: <code>{user_id}</code>\n\n"
            f"🌐 <b>Веб-кабина:</b> {dashboard_url}\n"
            f"⚡ <b>Telegram:</b> HOT-уведомления и быстрые действия\n\n{next_step}",
            reply_markup=main_menu() if has_access else None,
        )

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        dashboard_url = _dashboard_url(settings)
        web_hint = (
            "🌐 Кабина — кнопка в меню (WebApp)\n"
            if dashboard_url.startswith("https://")
            else "/web — адрес интерфейса Lead Radar\n"
        )
        await message.answer(
            "ℹ️ <b>Как пользоваться Lead Radar</b>\n\n"
            "/status — работает ли мониторинг\n"
            "/stats — контакты, лиды и сделки\n"
            "/pending — очередь AI_PENDING\n"
            "/hot — карточки открытых HOT-лидов\n"
            "/lead 12 — открыть лид №12\n"
            "/scan — проверить Instagram сейчас\n"
            "/competitors — кого отслеживаем\n"
            f"{web_hint}"
            "/cancel — отменить заполнение сделки\n\n"
            "Новые комментарии сохраняются автоматически. База данных — источник истины.",
            reply_markup=main_menu(),
        )

    @router.message(Command("pending"))
    async def pending_leads(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        cards = await workflow.list_ai_pending_leads(limit=8)
        if not cards:
            return await message.answer(
                "✅ Очередь AI_PENDING пуста.\n"
                f"Подробнее: {_dashboard_url(settings)}/radar?kind=pending",
                reply_markup=main_menu(),
            )
        await message.answer(
            f"🤖 <b>Ожидают AI-разбора: {len(cards)}</b>\n"
            f"Разбор в кабине: {_dashboard_url(settings)}/radar?kind=pending",
            reply_markup=main_menu(),
        )
        for card in cards:
            await message.answer(
                render_lead_card(card),
                reply_markup=lead_keyboard(card, web_public_url=_dashboard_url(settings)),
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
        search_state = "включён" if settings.lead_search_enabled else "приостановлен"
        notification_state = (
            f"настроено менеджеров: {len(settings.telegram_admin_chat_ids)}"
            if settings.telegram_admin_chat_ids
            else "не указаны TELEGRAM_ADMIN_CHAT_IDS"
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
            f"Поиск лидов: <b>{search_state}</b>\n"
            f"Уведомления: <b>{notification_state}</b>\n"
            f"Конкурентов: <b>{len(settings.competitors)}</b>\n"
            f"HOT-порог: <b>{settings.hot_lead_threshold}</b>"
        )

    @router.message(Command("scan"))
    async def scan(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        if not settings.lead_search_enabled:
            return await message.answer(
                "⏸ <b>Поиск лидов временно приостановлен</b>\n\n"
                "Ни ручные, ни фоновые проверки сейчас не запускаются. "
                "Внешние токены и лимиты не расходуются."
            )
        is_live = settings.instagram_provider not in {"mock", "replay"}
        if is_live and not settings.instagram_live_enabled:
            return await message.answer(
                "🛡 <b>Live-проверка заблокирована</b>\n\n"
                "Реальные Instagram-запросы выключены, поэтому токены не будут потрачены. "
                "Для разработки используйте replay/mock режим."
            )
        if is_live:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Подтвердить live-проверку", callback_data="scan:confirm"
                        )
                    ],
                    [InlineKeyboardButton(text="Отмена", callback_data="scan:cancel")],
                ]
            )
            return await message.answer(
                "⚠️ <b>Подтвердите расход внешних запросов</b>\n\n"
                f"Жёсткий предел одной проверки: <b>{settings.instagram_max_units_per_scan}</b> "
                "операций. Fallback входит в этот же лимит.\n"
                f"Дневной предел: <b>{settings.instagram_daily_request_limit}</b>.\n\n"
                "Если сейчас только тестируем интерфейс и CRM, запускать live-проверку не нужно.",
                reply_markup=keyboard,
            )
        await _start_scan_from_message(message, controller)

    @router.callback_query(F.data == "scan:confirm")
    async def confirm_scan(callback: CallbackQuery) -> None:
        if not authorized(callback):
            return await reject(callback)
        if not settings.lead_search_enabled:
            await callback.answer("Поиск лидов временно приостановлен", show_alert=True)
            return
        if settings.instagram_provider in {"mock", "replay"}:
            return await callback.answer("Live-подтверждение здесь не требуется", show_alert=True)
        if not settings.instagram_live_enabled:
            return await callback.answer("Live-запросы уже выключены", show_alert=True)
        if callback.message is None:
            return await callback.answer("Не удалось запустить проверку", show_alert=True)
        await callback.answer("Запускаю")
        await _start_scan_from_message(callback.message, controller)

    @router.callback_query(F.data == "scan:cancel")
    async def cancel_scan(callback: CallbackQuery) -> None:
        if not authorized(callback):
            return await reject(callback)
        if callback.message is not None:
            with contextlib.suppress(TelegramAPIError):
                await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Проверка отменена")

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        value = await workflow.get_stats()
        await message.answer(
            "📊 <b>Сводка Lead Radar</b>\n\n"
            f"👥 Контакты: <b>{value.contacts}</b>\n"
            f"💬 Комментарии: <b>{value.comments}</b>\n"
            f"🔥 HOT-лиды: <b>{value.hot_leads}</b>\n"
            f"📂 Открытые лиды: <b>{value.open_leads}</b>\n"
            f"✅ Продажи WON: <b>{value.won_deals}</b>\n"
            f"❌ Проиграны: <b>{value.lost_deals}</b>\n"
            f"🤖 Ожидают AI: <b>{value.ai_pending}</b>\n"
            f"📨 Уведомления в очереди: <b>{value.notification_backlog}</b>\n"
            f"💰 Выручка: <b>{value.revenue_uzs:,.0f} сум</b>\n\n"
            f"🌐 Подробнее: {_dashboard_url(settings)}",
            reply_markup=main_menu(),
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
            await message.answer(render_lead_card(card), reply_markup=lead_keyboard(card, web_public_url=_dashboard_url(settings)))

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
        await message.answer(render_lead_card(card), reply_markup=lead_keyboard(card, web_public_url=_dashboard_url(settings)))

    @router.message(Command("competitors"))
    async def competitors(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        await message.answer(
            "🏢 Конкуренты:\n" + "\n".join(escape(item) for item in settings.competitors)
        )

    @router.message(Command("web"))
    async def web(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        url = _dashboard_url(settings)
        webapp_hint = (
            "Кнопка «🌐 Кабина» открывает Mini App прямо в Telegram."
            if url.startswith("https://")
            else "Для Mini App нужен HTTPS public URL в WEB_PUBLIC_URL."
        )
        await message.answer(
            "🌐 <b>Lead Radar Web</b>\n\n"
            f"{escape(url)}\n\n"
            f"{webapp_hint}"
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
            await _refresh_visible_card(callback, workflow, settings)
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
            await _refresh_visible_card(callback, workflow, settings)
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


async def _start_scan_from_message(message: Message, controller: MonitorController) -> None:
    if not controller.start_cycle("manual"):
        await message.answer("⏳ Проверка уже выполняется. Откройте /status.")
        return
    await message.answer("🔎 Проверка Instagram запущена. Результат пришлю сюда после завершения.")
    task = asyncio.create_task(_report_scan_result(message, controller))
    task.add_done_callback(_consume_task_exception)


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
        f"Уведомлений об усилении интереса: {stats.change_notifications}\n"
        f"Ошибок: {stats.errors}"
    )


async def _refresh_visible_card(
    callback: CallbackQuery, workflow: LeadWorkflowService, settings: Settings
) -> None:
    if callback.message is None:
        return
    card = await workflow.get_lead_card(_callback_id(callback))
    try:
        await callback.message.edit_text(
            render_lead_card(card),
            reply_markup=lead_keyboard(card, web_public_url=_dashboard_url(settings)),
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
