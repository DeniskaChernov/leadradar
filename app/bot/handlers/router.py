from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.states import DealLostForm, DealWonForm
from app.config import Settings
from app.services.lead_workflow_service import (
    LeadAlreadyAssignedError,
    LeadWorkflowError,
    LeadWorkflowService,
)
from app.services.telegram_notification_service import TelegramLeadNotifier


def build_router(
    settings: Settings,
    workflow: LeadWorkflowService,
    notifier: TelegramLeadNotifier,
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
        await message.answer(
            "Lead Radar запущен.\n"
            f"Chat ID: <code>{message.chat.id}</code>\n"
            f"User ID: <code>{user_id}</code>\n\n"
            "Добавьте нужный ID в TELEGRAM_ADMIN_CHAT_IDS."
        )

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        await message.answer(
            "✅ Lead Radar работает\n"
            f"Provider: <b>{settings.instagram_provider}</b>\n"
            f"Competitors: <b>{len(settings.competitors)}</b>\n"
            f"HOT threshold: <b>{settings.hot_lead_threshold}</b>"
        )

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        value = await workflow.get_stats()
        await message.answer(
            "📊 <b>Статистика</b>\n\n"
            f"Контакты: {value.contacts}\n"
            f"Комментарии: {value.comments}\n"
            f"HOT leads: {value.hot_leads}\n"
            f"Открытые лиды: {value.open_leads}\n"
            f"Продажи: {value.won_deals}\n"
            f"Проиграны: {value.lost_deals}"
        )

    @router.message(Command("hot"))
    async def hot(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        cards = await workflow.list_hot_leads()
        if not cards:
            return await message.answer("Сейчас нет открытых HOT-лидов.")
        lines = ["🔥 <b>Открытые HOT-лиды</b>"]
        lines.extend(
            f"#{card.lead_id} · {card.score}/100 · @{card.username} · {card.status.value}"
            for card in cards
        )
        await message.answer("\n".join(lines))

    @router.message(Command("competitors"))
    async def competitors(message: Message) -> None:
        if not authorized(message):
            return await reject(message)
        await message.answer("🏢 Конкуренты:\n" + "\n".join(settings.competitors))

    @router.callback_query(F.data.startswith("lead:take:"))
    async def take_lead(callback: CallbackQuery) -> None:
        if not authorized(callback):
            return await reject(callback)
        lead_id = _callback_id(callback)
        try:
            await workflow.assign_manager(lead_id, callback.from_user.id)
            await notifier.refresh_lead_messages(lead_id)
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
        deal = await workflow.win_deal(
            int(data["deal_id"]),
            message.from_user.id,
            product_name=str(data["product_name"]),
            amount=Decimal(str(data["amount"])),
            quantity=quantity,
        )
        await state.clear()
        await notifier.refresh_lead_messages(deal.lead_id or 0)
        await message.answer(f"✅ Сделка #{deal.id} отмечена как WON.")

    @router.callback_query(F.data.startswith("deal:lost:"))
    async def lost_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not authorized(callback):
            return await reject(callback)
        await state.set_state(DealLostForm.reason)
        await state.update_data(deal_id=_callback_id(callback))
        if callback.message:
            await callback.message.answer(
                "Укажите причину: дорого / нет нужного товара / нет нужного цвета / "
                "нет в наличии / долго ждать / не отвечает / купил у конкурента / "
                "отложил покупку / другое"
            )
        await callback.answer()

    @router.message(DealLostForm.reason)
    async def lost_reason(message: Message, state: FSMContext) -> None:
        if not authorized(message):
            return await reject(message)
        reason = (message.text or "").strip()
        if not reason:
            return await message.answer("Причина не может быть пустой.")
        data = await state.get_data()
        deal = await workflow.lose_deal(
            int(data["deal_id"]), message.from_user.id, reason=reason
        )
        await state.clear()
        await notifier.refresh_lead_messages(deal.lead_id or 0)
        await message.answer(f"❌ Сделка #{deal.id} отмечена как LOST.")

    return router


def _callback_id(callback: CallbackQuery) -> int:
    if callback.data is None:
        raise LeadWorkflowError("Callback data is missing")
    try:
        return int(callback.data.rsplit(":", maxsplit=1)[1])
    except (IndexError, ValueError) as exc:
        raise LeadWorkflowError("Invalid callback data") from exc
