"""Хелперы UI для карточек лидов (бейджи качества, фильтры)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.db.models import Lead, LeadStatus


def lead_analysis_details(lead: Lead) -> dict:
    details = lead.analysis_details
    return details if isinstance(details, dict) else {}


def confidence_percent(value: object) -> int | None:
    """Native integer percentages and legacy fractional values, without fake defaults."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or not 0 <= number <= 100:
        return None
    integer_format = isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit())
    if not integer_format and number <= 1:
        number *= 100
    return int(number.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def lead_confidence(lead: Lead) -> int | None:
    details = lead_analysis_details(lead)
    factors = details.get('factors')
    factors = factors if isinstance(factors, dict) else {}
    for value in (details.get('confidence'), details.get('confidence_score'), factors.get('confidence_score')):
        if value is not None:
            return confidence_percent(value)
    return None


def lead_is_off_catalog(lead: Lead) -> bool:
    """Лид отмечен как вне каталога мебели/ротанга."""
    details = lead_analysis_details(lead)
    flags = details.get("risk_flags") or []
    reason = (lead.ai_reason or "").lower()
    return "Не наш ассортимент" in flags or "вне каталога" in reason


def lead_is_garbage(lead: Lead) -> bool:
    """Garbage lead: NOT_LEAD, off-catalog, or explicit reaction/spam."""
    if lead.status == LeadStatus.NOT_LEAD:
        return True
    if lead_is_off_catalog(lead):
        return True
    return str(lead.intent or "") in {"REACTION", "SPAM"}


def lead_next_action_overdue(lead: Lead, *, now: datetime | None = None) -> bool:
    """True, если next_action_at в прошлом (SLA просрочен)."""
    due = lead.next_action_at
    if due is None:
        return False
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    return due < clock


def lead_quality_badge(lead: Lead) -> str | None:
    """Короткая метка для UI или None."""
    if lead_is_off_catalog(lead):
        return "off_catalog"
    if lead.status == LeadStatus.NOT_LEAD:
        return "not_lead"
    if lead.status == LeadStatus.AI_PENDING:
        return "ai_pending"
    if str(lead.intent or "") in {"REACTION", "SPAM"}:
        return "noise"
    return None
