import asyncio

from sqlalchemy import func, select

from app.db.models import (
    ContactEvent,
    ContactEventType,
    SignificantChange,
    SignificantChangeNotification,
)
from app.schemas.instagram import InstagramComment
from app.services.audience_service import AudienceEngine
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.significant_change_service import (
    IntelligenceSnapshot,
    SignificantChangeDetector,
)
from app.services.telegram_notification_service import TelegramLeadNotifier
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer
from tests.test_notifications import RecordingBot


def _service(session_factory):
    audience = AudienceEngine(session_factory, hot_threshold=70)
    detector = SignificantChangeDetector(session_factory, hot_threshold=70)
    return LeadService(
        session_factory,
        StaticAnalyzer(),
        hot_threshold=70,
        audience_engine=audience,
        change_detector=detector,
    )


async def test_new_competitor_creates_one_material_change_for_existing_contact(
    session_factory,
):
    contacts = ContactService(session_factory)
    service = _service(session_factory)
    first = await contacts.persist_signal(make_post(), make_comment("change-first"))
    first_result = await service.process_signal(first)
    assert first_result is not None and first_result.significant_change_id is None

    second_post = make_post().model_copy(
        update={
            "platform_post_id": "change-second-post",
            "competitor": "chinar.uz",
            "url": "https://www.instagram.com/reel/change-second-post/",
        }
    )
    second_comment = make_comment("change-second").model_copy(
        update={"text": "Есть в наличии?"}
    )
    second = await contacts.persist_signal(second_post, second_comment)
    result = await service.process_signal(second)
    duplicate = await service.process_signal(second)

    assert result is not None and result.significant_change_id is not None
    assert duplicate is not None and duplicate.significant_change_id is None
    async with session_factory() as session:
        change = await session.scalar(select(SignificantChange))
        assert change is not None
        assert "NEW_COMPETITOR" in change.change_types_json
        assert change.current_priority >= change.previous_priority
        assert await session.scalar(select(func.count(SignificantChange.id))) == 1
        assert (
            await session.scalar(
                select(func.count(ContactEvent.id)).where(
                    ContactEvent.event_type == ContactEventType.SIGNIFICANT_CHANGE
                )
            )
            == 1
        )


def test_weak_score_noise_does_not_become_material_change():
    detector = SignificantChangeDetector(None, hot_threshold=70)  # type: ignore[arg-type]
    before = IntelligenceSnapshot(
        signal_count=2,
        commercial_signal_count=1,
        competitor_count=1,
        activity_score=30,
        value_score=55,
        fit_score=55,
        commercial_stage="CONSIDERATION",
        intent_strength=55,
        customer_type="B2C",
        quantity_band=None,
        products=("TABLE",),
        intents=("PRICE",),
        audiences=("tables",),
    )
    after = IntelligenceSnapshot(
        signal_count=3,
        commercial_signal_count=2,
        competitor_count=1,
        activity_score=34,
        value_score=59,
        fit_score=59,
        commercial_stage="CONSIDERATION",
        intent_strength=59,
        customer_type="B2C",
        quantity_band=None,
        products=("TABLE",),
        intents=("PRICE",),
        audiences=("tables",),
    )
    assert detector._detect(before, after) == []


def test_business_quantity_and_stage_transition_are_material():
    detector = SignificantChangeDetector(None, hot_threshold=70)  # type: ignore[arg-type]
    before = IntelligenceSnapshot(
        signal_count=3,
        commercial_signal_count=1,
        competitor_count=1,
        activity_score=35,
        value_score=60,
        fit_score=60,
        commercial_stage="CONSIDERATION",
        intent_strength=60,
        customer_type="B2C",
        quantity_band=None,
        products=("CHAIRS",),
        intents=("PRICE",),
        audiences=("chairs",),
    )
    after = IntelligenceSnapshot(
        signal_count=4,
        commercial_signal_count=2,
        competitor_count=1,
        activity_score=72,
        value_score=88,
        fit_score=88,
        commercial_stage="READY_TO_BUY",
        intent_strength=88,
        customer_type="B2B",
        quantity_band="50_PLUS",
        products=("CHAIRS",),
        intents=("PRICE", "QUANTITY"),
        audiences=("chairs", "b2b", "quantity-50", "hot-7d"),
    )
    changes = detector._detect(before, after)
    assert {
        "NEW_STRONG_INTENT",
        "SIGNIFICANT_QUANTITY",
        "B2B_DETECTED",
        "ENTERED_HOT",
        "ENTERED_HIGH_VALUE",
        "VALUE_INCREASE",
        "STAGE_ADVANCED",
    } <= set(changes)


async def test_material_change_notification_outbox_is_idempotent(session_factory):
    contacts = ContactService(session_factory)
    service = _service(session_factory)
    first = await contacts.persist_signal(make_post(), make_comment("notify-change-first"))
    await service.process_signal(first)
    second_post = make_post().model_copy(
        update={
            "platform_post_id": "notify-change-post",
            "competitor": "dafna.uz",
            "url": "https://www.instagram.com/reel/notify-change-post/",
        }
    )
    second = await contacts.persist_signal(
        second_post,
        InstagramComment(
            **make_comment("notify-change-second").model_dump(exclude={"text"}),
            text="Нархи қанча?",
        ),
    )
    result = await service.process_signal(second)
    assert result is not None and result.significant_change_id is not None

    bot = RecordingBot()
    notifier = TelegramLeadNotifier(
        bot,
        session_factory,
        LeadWorkflowService(session_factory, 70),
        [1001],
        hot_threshold=70,
    )
    sent = await asyncio.gather(
        notifier.notify_significant_change(result.significant_change_id),
        notifier.notify_significant_change(result.significant_change_id),
    )

    assert sum(sent) == 1
    assert len(bot.sent) == 1
    assert "Лид стал горячее" in bot.sent[0][1]
    async with session_factory() as session:
        assert (
            await session.scalar(select(func.count(SignificantChangeNotification.id)))
            == 1
        )
