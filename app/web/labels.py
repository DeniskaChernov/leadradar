from __future__ import annotations

LEAD_STATUS_LABELS = {
    "ANALYZING": "Анализируем",
    "AI_PENDING": "Нужна дополнительная проверка",
    "NEW": "Новый",
    "TAKEN": "В работе",
    "CONTACTED": "Связались",
    "QUALIFIED": "Интерес подтверждён",
    "OFFER_SENT": "Предложение отправлено",
    "NEGOTIATION": "Переговоры",
    "WON": "Продажа",
    "LOST": "Проигран",
    "NOT_LEAD": "Не лид",
}

DEAL_STATUS_LABELS = {
    "NEW": "Новая сделка",
    "QUALIFIED": "Интерес подтверждён",
    "OFFER_SENT": "Предложение отправлено",
    "NEGOTIATION": "Переговоры",
    "WON": "Продажа",
    "LOST": "Проиграна",
}

INTENT_LABELS = {
    "BUY": "Хочет купить",
    "PRICE": "Спрашивает цену",
    "AVAILABILITY": "Уточняет наличие",
    "DELIVERY": "Спрашивает доставку",
    "QUANTITY": "Уточняет количество",
    "COLOR": "Уточняет цвет",
    "SIZE": "Уточняет размер",
    "LOCATION": "Ищет адрес / шоурум",
    "CATALOG": "Просит каталог",
    "CONTACT": "Просит связаться",
    "QUESTION": "Вопрос по товару",
    "REACTION": "Реакция",
    "SPAM": "Спам",
    "OTHER": "Другое",
}

PRODUCT_LABELS = {
    "DINING_SET": "Обеденный комплект",
    "RATTAN_SOFA": "Диван плетёный",
    "RATTAN_ARMCHAIR": "Кресло плетёное",
    "RATTAN_GARDEN_SET": "Садовый гарнитур ротанг",
    "RATTAN_BAR_STOOL": "Барный стул",
    "SWING": "Качели",
    "PERGOLA": "Пергола / беседка",
    "RATTAN_FURNITURE": "Плетёная мебель (ротанг)",
    "CHAIRS": "Стулья / кресла",
    "TABLE": "Стол",
    "OUTDOOR_FURNITURE": "Мебель для сада / террасы",
    "HORECA": "Мебель HoReCa",
}

AI_SOURCE_LABELS = {
    "local_rules": "Локальные правила · бесплатно",
    "openai_or_cache": "OpenAI / сохранённый AI-ответ",
    "pending": "Ожидает дополнительного анализа",
    "custom_analyzer": "Системный анализатор",
}

FUNNEL_STAGE_LABELS = {
    "NON_COMMERCIAL": "Нет покупательского намерения",
    "AWARENESS": "Знакомство с товаром",
    "CONSIDERATION": "Сравнивает и выбирает",
    "PURCHASE_INTENT": "Намерение купить",
    "READY_TO_BUY": "Готов к покупке",
}

URGENCY_LABELS = {
    "LOW": "Низкая",
    "MEDIUM": "Средняя",
    "HIGH": "Высокая",
}

PURCHASE_HORIZON_LABELS = {
    "TODAY": "Сегодня",
    "THIS_WEEK": "На этой неделе",
    "THIS_MONTH": "В этом месяце",
    "RESEARCHING": "Пока выбирает",
    "UNKNOWN": "Не определён",
}

COMMERCIAL_STAGE_LABELS = {
    "NON_COMMERCIAL": "Коммерческий интерес не подтверждён",
    "AWARENESS": "Знакомится с товаром",
    "CONSIDERATION": "Сравнивает предложения",
    "PURCHASE_INTENT": "Планирует покупку",
    "READY_TO_BUY": "Готов к покупке",
}

EXPORT_ELIGIBILITY_LABELS = {
    "NOT_EXPORTABLE": "Не экспортируется",
    "FIRST_PARTY_ELIGIBLE": "Есть допустимый first-party контакт",
    "EXPORTED": "Экспортирован",
}

COVERAGE_LABELS = {
    "FULL": "Получено полностью",
    "PARTIAL": "Получено частично",
    "LATEST_ONLY": "Только последние комментарии",
    "UNKNOWN": "Полнота неизвестна",
}

EVENT_LABELS = {
    "COMMENT_FOUND": "Найден комментарий",
    "LEAD_CREATED": "Создан лид",
    "LEAD_SCORE_CHANGED": "Изменилась оценка лида",
    "MANAGER_ASSIGNED": "Лид взят в работу",
    "MANAGER_MARKED_NOT_LEAD": "Помечен как не лид",
    "CONTACTED": "Связались с клиентом",
    "CUSTOMER_REPLIED": "Клиент ответил",
    "NOTE_ADDED": "Добавлена заметка",
    "PRODUCT_INTEREST_ADDED": "Уточнён интерес",
    "OFFER_SENT": "Отправлено предложение",
    "NEGOTIATION_STARTED": "Начались переговоры",
    "DEAL_CREATED": "Создана сделка",
    "DEAL_WON": "Сделка выиграна",
    "DEAL_LOST": "Сделка проиграна",
    "LEAD_STATUS_CHANGED": "Изменилась стадия лида",
    "NEXT_CONTACT_SCHEDULED": "Запланирован следующий контакт",
    "NEXT_CONTACT_COMPLETED": "Задача выполнена",
    "NEXT_CONTACT_CANCELLED": "Задача отменена",
    "QUALIFICATION_UPDATED": "Обновлена информация о клиенте",
    "LEAD_REOPENED": "Лид возвращён в работу",
    "SIGNIFICANT_CHANGE": "Лид стал горячее",
    "AUDIENCE_EXPORT_PREVIEW": "Dry-run экспорта аудитории",
}

CHANGE_TYPE_LABELS = {
    "NEW_COMPETITOR": "Новый конкурент",
    "NEW_STRONG_INTENT": "Новое сильное намерение",
    "NEW_PRODUCT": "Новая товарная категория",
    "SIGNIFICANT_QUANTITY": "Значимое количество",
    "B2B_DETECTED": "Обнаружен B2B / HoReCa",
    "ENTERED_HOT": "Вошёл в HOT",
    "ENTERED_HIGH_VALUE": "Стал high-value",
    "REACTIVATED": "Вернулся после паузы",
    "VALUE_INCREASE": "Приоритет вырос",
    "STAGE_ADVANCED": "Новая стадия покупки",
}

CHANNEL_LABELS = {
    "instagram": "Instagram",
    "telegram": "Telegram",
    "phone": "Телефон",
    "whatsapp": "WhatsApp",
    "other": "Другой канал",
}

BUYER_ROLE_LABELS = {
    "B2C_CONSUMER": "Розничный покупатель",
    "B2B_HORECA": "B2B / HoReCa",
    "DESIGNER_CONTRACTOR": "Дизайнер / комплектатор",
    "JOB_SEEKER": "Ищет работу",
    "UNKNOWN": "Не определено",
}

BUYER_ROLE_ICONS = {
    "B2C_CONSUMER": "🛍️",
    "B2B_HORECA": "🏨",
    "DESIGNER_CONTRACTOR": "📐",
    "JOB_SEEKER": "💼",
    "UNKNOWN": "❓",
}

QUALIFICATION_FIELD_LABELS = {
    "phone": "Телефон",
    "preferred_channel": "Удобный канал",
    "city": "Город",
    "interest_summary": "Что ищет",
    "desired_quantity": "Количество",
    "budget_from": "Бюджет от",
    "budget_to": "Бюджет до",
    "desired_color": "Цвет",
    "purchase_timeline": "Когда планирует покупку",
    "qualification_note": "Комментарий менеджера",
}

RUN_STATUS_LABELS = {
    "RUNNING": "Выполняется",
    "SUCCESS": "Успешно",
    "FAILED": "Ошибка",
}

TRIGGER_LABELS = {
    "schedule": "По расписанию",
    "web": "Вручную из Mini App",
    "manual": "Вручную",
    "bot": "Из Telegram",
    "once": "Разовая проверка",
}

COMPETITOR_CATEGORY_LABELS = {
    "DIRECT": "Прямой конкурент",
    "DINING": "Обеденные группы",
    "OUTDOOR": "Сад / терраса",
    "HORECA": "HoReCa",
    "PREMIUM": "Премиум / интерьер",
    "MASS": "Массовый рынок",
}

AUDIENCE_HEALTH_LABELS = {
    "HEALTHY": "Здоровая",
    "LOW_DATA": "Мало данных",
    "STALE": "Устарела",
    "NEEDS_REVIEW": "На проверке",
    "NOT_EXPORTABLE": "Не для экспорта",
    "NOISY": "Шумная",
}

BUDGET_STATUS_LABELS = {
    "HEALTHY": "В норме",
    "WATCH": "Наблюдение",
    "UNKNOWN": "Неизвестно",
    "NOT_CONFIGURED": "Не задан",
    "DANGER": "Опасно",
}


def label(mapping: dict[str, str], value: object, fallback: str = "—") -> str:
    if value is None:
        return fallback
    key = getattr(value, "value", value)
    return mapping.get(str(key), str(key).replace("_", " ").title())

