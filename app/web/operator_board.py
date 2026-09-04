"""Операторская доска лидов: укрупнённые колонки дневного контура."""

from __future__ import annotations

from typing import Any

# Одна доска для мебели и ротанга. drop_status — куда двигаем при DnD
# (цепочку переходов закрывает CRMService.move_lead_toward).
OPERATOR_BOARD_COLUMNS: list[dict[str, Any]] = [
    {
        "key": "pending",
        "title": "Оценка",
        "hint": "Система / GPT",
        "statuses": ["ANALYZING", "AI_PENDING"],
        "drop_status": None,
        "closed": False,
        "pending": True,
    },
    {
        "key": "new",
        "title": "Новый",
        "hint": "Взять в работу",
        "statuses": ["NEW"],
        "drop_status": None,
        "closed": False,
        "pending": False,
    },
    {
        "key": "working",
        "title": "В работе",
        "hint": "Взяли · связались · интерес",
        "statuses": ["TAKEN", "CONTACTED", "QUALIFIED"],
        "drop_status": "TAKEN",
        "closed": False,
        "pending": False,
    },
    {
        "key": "offer",
        "title": "Предложение",
        "hint": "Текст ушёл клиенту",
        "statuses": ["OFFER_SENT"],
        "drop_status": "OFFER_SENT",
        "closed": False,
        "pending": False,
    },
    {
        "key": "deal",
        "title": "Переговоры",
        "hint": "До продажи",
        "statuses": ["NEGOTIATION"],
        "drop_status": "NEGOTIATION",
        "closed": False,
        "pending": False,
    },
    {
        "key": "closed",
        "title": "Закрыто",
        "hint": "Продажа / отказ",
        "statuses": ["WON", "LOST"],
        "drop_status": None,
        "closed": True,
        "pending": False,
    },
]


def rows_by_operator_column(
    rows: list,
    columns: list[dict[str, Any]] | None = None,
) -> dict[str, list]:
    """Группировка строк лида по ключу операторской колонки."""
    cols = columns or OPERATOR_BOARD_COLUMNS
    status_to_key: dict[str, str] = {}
    for col in cols:
        for status in col["statuses"]:
            status_to_key[status] = col["key"]
    grouped: dict[str, list] = {col["key"]: [] for col in cols}
    for row in rows:
        stage = row[0].status.value
        key = status_to_key.get(stage)
        if key is not None:
            grouped[key].append(row)
    return grouped
