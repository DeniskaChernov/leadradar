"""Advice and endorsements must not turn a weak 'kerak' into a HOT order."""

import pytest
from sqlalchemy import select

from app.db.models import (
    Comment,
    ContactEvent,
    Lead,
    LeadStatus,
    NotificationLog,
    NotificationStatus,
    Post,
)
from app.schemas.leads import Intent
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.audience_service import AudienceEngine
from app.services.lead_service import LeadService
from tests.test_lead_workflow import create_lead


@pytest.mark.parametrize("comment", [
    "Chinor barbir chinor yuqori sifat yuqori daraja odam honodoni uchun olayotganda adashmaslik kerak chinor barbir chinor.",
    "Sifatli mebel, tanlashda aldanmaslik kerak!",
    "Мебель олишда адашмаслик керак, Чинор яхши",
    "Мебель танлашда алданмаслик керак",
])
async def test_generic_purchase_advice_is_not_hot(comment):
    result = await RuleBasedLeadAnalyzer().analyze(LeadAnalysisContext(
        competitor="public_furniture", post_caption="Обеденный стол и стулья",
        comment=comment, username="public_comment", previous_signals=[], previous_interests=[],
    ))
    assert result.lead_score < 70
    assert result.intent != Intent.BUY


@pytest.mark.parametrize(("comment", "intent"), [
    ("Menga stul kerak", Intent.BUY),
    ("Стул керак", Intent.BUY),
    ("Kerak", Intent.BUY),
    ("Adashmaslik kerak, narxi qancha?", Intent.PRICE),
    ("Aldanmaslik kerak, menga stul kerak", Intent.BUY),
    ("Адашмаслик керак, нархи қанча?", Intent.PRICE),
    ("Olmoqchiman, adashmaslik kerak", Intent.BUY),
])
async def test_actual_request_alongside_advice_keeps_its_intent(comment, intent):
    result = await RuleBasedLeadAnalyzer().analyze(LeadAnalysisContext(
        competitor="public_furniture", post_caption="Обеденный стол и стулья",
        comment=comment, username="public_comment", previous_signals=[], previous_interests=[],
    ))
    assert result.is_lead and result.lead_score >= 70
    assert result.intent == intent


async def test_existing_advice_can_be_corrected_locally_without_erasing_history(session_factory):
    lead_id = await create_lead(session_factory)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        comment = await session.get(Comment, lead.comment_id)
        comment.text = "Chinor barbir chinor yuqori sifat odam honodoni uchun olayotganda adashmaslik kerak."
        (await session.get(Post, comment.post_id)).caption = "Обеденный стол и стулья"
        lead.lead_score = 90
        lead.ai_source = "local_rules"
        session.add(NotificationLog(idempotency_key=f"lead:{lead_id}:chat:1001",
                                    lead_id=lead_id, chat_id=1001, status=NotificationStatus.SENT))
        await session.commit()
        original_text = comment.text
        event_ids = set(await session.scalars(select(ContactEvent.id)))
    service = LeadService(session_factory, RuleBasedLeadAnalyzer(), 70,
                          audience_engine=AudienceEngine(session_factory, 70))
    result = await service.analyze_lead(lead_id, local_only=True)
    assert result.status == LeadStatus.NOT_LEAD and not result.is_hot
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert (await session.get(Comment, lead.comment_id)).text == original_text
        assert event_ids <= set(await session.scalars(select(ContactEvent.id)))
        notifications = list(await session.scalars(select(NotificationLog)))
        assert len(notifications) == 1 and notifications[0].status == NotificationStatus.SENT
