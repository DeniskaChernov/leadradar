from app.db.models import Lead, LeadStatus
from app.web.lead_ui_helpers import lead_is_off_catalog, lead_quality_badge


def test_lead_is_off_catalog_from_risk_flags():
    lead = Lead(
        contact_id=1,
        comment_id=1,
        competitor_id=1,
        intent="OTHER",
        lead_score=8,
        status=LeadStatus.NOT_LEAD,
        analysis_details={"risk_flags": ["Не наш ассортимент"]},
        ai_reason="Запрос относится к товару вне каталога мебели и ротанга.",
    )
    assert lead_is_off_catalog(lead) is True
    assert lead_quality_badge(lead) == "off_catalog"


def test_lead_quality_badge_not_lead():
    lead = Lead(
        contact_id=1,
        comment_id=1,
        competitor_id=1,
        intent="PRICE",
        lead_score=40,
        status=LeadStatus.NOT_LEAD,
        ai_reason="Не лид",
    )
    assert lead_quality_badge(lead) == "not_lead"


def test_lead_quality_badge_none_for_commercial():
    lead = Lead(
        contact_id=1,
        comment_id=1,
        competitor_id=1,
        intent="PRICE",
        lead_score=86,
        status=LeadStatus.NEW,
        ai_reason="Пользователь спрашивает цену товара.",
    )
    assert lead_quality_badge(lead) is None
