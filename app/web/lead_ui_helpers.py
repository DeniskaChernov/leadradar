"""Хелперы UI для карточек лидов (бейджи качества, фильтры)."""

from __future__ import annotations

from app.db.models import Lead, LeadStatus


def lead_analysis_details(lead: Lead) -> dict:
    details = lead.analysis_details
    return details if isinstance(details, dict) else {}


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
