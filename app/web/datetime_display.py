"""Форматирование UTC-дат из БД в локальный часовой пояс UI."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def format_display_dt(
    value: datetime | None,
    fmt: str = "%d.%m %H:%M",
    *,
    timezone: str = "Asia/Tashkent",
) -> str:
    if value is None:
        return "—"
    dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return dt.astimezone(ZoneInfo(timezone)).strftime(fmt)


def parse_display_dt(value: str, *, timezone: str = "Asia/Tashkent") -> datetime:
    """Naive datetime-local из UI трактуем как локальный TZ оператора, сохраняем UTC."""
    raw = value.strip()
    if not raw:
        raise ValueError("empty datetime")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        return dt.astimezone(UTC)
    local = dt.replace(tzinfo=ZoneInfo(timezone))
    return local.astimezone(UTC)


def deadline_overdue(value: datetime | None, now: datetime) -> bool:
    """SQLite returns naive UTC values; compare instants consistently with PostgreSQL."""
    if value is None:
        return False
    due = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    clock = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    return due < clock
