from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import Comment, Contact, ContactEvent, Lead, LeadStatus, OpeningSignal, Vertical
from app.services.contact_service import ContactService
from app.services.crm_service import CRMService
from app.services.hot_outreach_service import HotOutreachService
from app.services.lead_service import LeadService
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.services.place_opening_service import PlaceOpeningService
from app.services.product_catalog_service import ProductCatalogService
from app.services.usage_service import ExternalUsageService
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_contact_service import make_comment, make_post
from tests.test_lead_service import StaticAnalyzer
from tests.test_live_scan_guard import FakeMonitor


@pytest.mark.parametrize(("text", "city", "timeline"), [
    ("Открываем кафе в Ташкенте в следующем месяце", "Tashkent", "В СЛЕДУЮЩЕМ МЕСЯЦЕ"),
    ("Открываем ресторан в Бухаре на следующей неделе", "Bukhara", "НА СЛЕДУЮЩЕЙ НЕДЕЛЕ"),
    ("Samarqandda yangi kafe ochamiz kelasi oy", "Samarkand", "В СЛЕДУЮЩЕМ МЕСЯЦЕ"),
    ("Namanganda yangi restoran, kelasi hafta ochilishi", "Namangan", "НА СЛЕДУЮЩЕЙ НЕДЕЛЕ"),
    ("Открываем кафе, нужны столы", None, None),
    ("Открываем кафе, везём из Ташкента в Бухару", None, None),
])
def test_opening_location_and_timeline_require_evidence(text, city, timeline):
    result = PlaceOpeningService.detect_opening_signals(text)
    assert result is not None
    assert result["city"] == city
    assert result["opening_timeline"] == timeline
    assert result["place_name"].startswith("Новый объект")


@pytest.mark.parametrize("text", [
    "Цена?", "Поздравляю с открытием кафе!", "Не открываем ресторан",
    "Когда открытие кафе?", "Открываем профиль, где цена?", "Открытие кафе отменено",
])
def test_dont_attribute_competitor_opening_or_congratulations_to_commenter(text):
    assert PlaceOpeningService.detect_opening_signals(
        text, caption_text="Открываем новый ресторан в Ташкенте"
    ) is None


async def _opening_lead(factory, comment_id="opening-auto", text='Открываем кафе «Bon» в Бухаре'):
    signal = await ContactService(factory).persist_signal(
        make_post(), make_comment(comment_id).model_copy(update={"text": text}),
    )
    prepared = await LeadService(factory, StaticAnalyzer(), 70).ensure_analyzing(signal)
    return signal, prepared


async def test_opening_committed_with_lead_before_analysis_and_repeat(session_factory):
    signal, prepared = await _opening_lead(session_factory)
    service = PlaceOpeningService(session_factory)
    queue = await service.get_review_queue()
    assert len(queue) == 1
    opening = queue[0]
    assert opening.lead_id == prepared.lead_id
    assert opening.contact_id == signal.contact_id
    assert opening.city == "Bukhara"
    assert opening.place_name == "Cafe «Bon»"
    assert opening.source_type == "INSTAGRAM_PUBLIC_COMMENT"
    async with session_factory() as session:
        lead = await session.get(Lead, prepared.lead_id)
        assert lead.status == LeadStatus.ANALYZING
        assert lead.opening_checked_at is not None
        events_before = await session.scalar(select(func.count(ContactEvent.id)))
    await LeadService(session_factory, StaticAnalyzer(), 70).ensure_analyzing(signal)
    await service.review_opening_signal(opening.id, 1, "VERIFIED")
    assert await service.backfill_saved_leads() == {"checked": 0, "created": 0}
    # Another comment about the same named venue must not reset its review.
    await _opening_lead(session_factory, "opening-repeat")
    async with session_factory() as session:
        assert await session.scalar(select(func.count(OpeningSignal.id))) == 1
        assert await session.scalar(select(func.count(ContactEvent.id))) == events_before + 2
        saved = await session.get(OpeningSignal, opening.id)
        assert saved.review_status == "VERIFIED"


async def test_opening_rolls_back_with_lead_transaction(file_session_factory):
    signal = await ContactService(file_session_factory).persist_signal(make_post(), make_comment())
    async with file_session_factory() as session:
        comment = await session.get(Comment, signal.comment_id)
        comment.text = "Открываем кафе в Бухаре"
        lead = Lead(contact_id=signal.contact_id, comment_id=signal.comment_id,
                    competitor_id=signal.competitor_id, lead_score=0, intent="OTHER")
        session.add(lead)
        await session.flush()
        assert await PlaceOpeningService.capture_lead(session, lead, comment)
        await session.rollback()
    async with file_session_factory() as session:
        assert await session.scalar(select(func.count(OpeningSignal.id))) == 0
        assert await session.scalar(select(func.count(Lead.id))) == 0


async def test_opening_backfill_is_bounded_idempotent_and_preserves_history(session_factory):
    await _opening_lead(session_factory, "historic-1", "Открываем кафе, нужны столы")
    await _opening_lead(session_factory, "historic-2", "Сколько стоит?")
    await _opening_lead(session_factory, "historic-3", "Открываем отель в Бухаре")
    async with session_factory() as session:
        from sqlalchemy import delete
        await session.execute(delete(OpeningSignal))
        leads = list(await session.scalars(select(Lead).order_by(Lead.id)))
        for lead in leads:
            lead.opening_checked_at = None
        old = await session.get(Comment, leads[-1].comment_id)
        old.created_at_platform = datetime.now(UTC) - timedelta(days=31)
        await session.commit()
        before = [(lead.id, lead.updated_at) for lead in leads]
        event_ids = list(await session.scalars(select(ContactEvent.id).order_by(ContactEvent.id)))
    service = PlaceOpeningService(session_factory)
    assert await service.backfill_saved_leads(batch_size=1) == {"checked": 2, "created": 1}
    assert await service.backfill_saved_leads(batch_size=1) == {"checked": 0, "created": 0}
    queue = await service.get_review_queue()
    assert len(queue) == 1 and queue[0].city is None
    async with session_factory() as session:
        after = (await session.execute(select(Lead.id, Lead.updated_at).order_by(Lead.id))).all()
        assert [(i, t.replace(tzinfo=UTC)) for i, t in after] == [(i, t.replace(tzinfo=UTC)) for i, t in before]
        assert list(await session.scalars(select(ContactEvent.id).order_by(ContactEvent.id))) == event_ids


async def _many_hot(factory, count=125):
    signal = await ContactService(factory).persist_signal(make_post(), make_comment())
    now = datetime.now(UTC)
    async with factory() as session:
        contacts = [Contact(platform="instagram", platform_user_id=f"hot-many-{i}",
                            username=f"hot_many_{i}", normalized_username=f"hot_many_{i}",
                            profile_url=f"https://instagram.com/hot_many_{i}/") for i in range(count)]
        session.add_all(contacts)
        await session.flush()
        comments = [Comment(platform_comment_id=f"hot-many-{i}", post_id=signal.post_id,
                            contact_id=contact.id, competitor_id=signal.competitor_id,
                            text="Нужны стулья", created_at_platform=now)
                    for i, contact in enumerate(contacts)]
        session.add_all(comments)
        await session.flush()
        leads = [Lead(contact_id=contact.id, comment_id=comment.id,
                      competitor_id=signal.competitor_id, lead_score=85,
                      status=LeadStatus.NEW, intent="OTHER", created_at=now)
                 for contact, comment in zip(contacts, comments, strict=True)]
        session.add_all(leads)
        await session.commit()
        return [lead.id for lead in leads]


def _hot(factory):
    return HotOutreachService(factory, hot_threshold=70,
                              workflow=LeadWorkflowService(factory, 70),
                              crm=CRMService(factory), catalog=ProductCatalogService(factory))


async def test_hot_pagination_exact_count_and_consistent_filters(session_factory):
    ids = await _many_hot(session_factory)
    service = _hot(session_factory)
    assert await service.queue_count(vertical="FURNITURE") == 125
    actual = []
    for offset in range(0, 160, 40):
        actual.extend(item["lead_id"] for item in await service.queue(limit=40, offset=offset))
    assert actual == list(reversed(ids))
    async with session_factory() as session:
        (await session.get(Lead, ids[0])).vertical = Vertical.ARTIFICIAL_RATTAN
        (await session.get(Lead, ids[1])).status = LeadStatus.WON
        stale = await session.get(Lead, ids[2])
        (await session.get(Comment, stale.comment_id)).created_at_platform = datetime.now(UTC) - timedelta(days=31)
        await session.commit()
    assert await service.queue_count(vertical="FURNITURE") == 122
    assert await service.queue_count(vertical="ARTIFICIAL_RATTAN") == 1
    assert len(await service.queue(vertical="FURNITURE", limit=200)) == 122


async def test_next_hot_and_priority_search_beyond_first_eighty(session_factory):
    ids = await _many_hot(session_factory)
    async with session_factory() as session:
        leads = list(await session.scalars(select(Lead).order_by(Lead.id)))
        for lead in leads[1:]:
            lead.lead_score = 100
            lead.analysis_details = {"hot_outreach": {"message": "Уже отправлено", "sent_at": "2026-10-06"}}
        await session.commit()
    service = _hot(session_factory)
    assert (await service.queue(limit=1))[0]["lead_id"] == ids[0]
    assert await service.next_queue_lead_id() == ids[0]
    assert await service.next_queue_lead_id(exclude_lead_id=ids[0]) is None
    # A higher scoring new signal from a previously contacted author stays behind a new author.
    async with session_factory() as session:
        prior = await session.get(Lead, ids[1])
        new = await session.get(Lead, ids[2])
        new.contact_id = prior.contact_id
        new.analysis_details = {}
        await session.commit()
    queue = await service.queue(limit=200)
    assert queue[0]["lead_id"] == ids[0]
    assert next(item for item in queue if item["lead_id"] == ids[2])["already_contacted"]
    assert await service.next_queue_lead_id(exclude_lead_id=ids[0]) is None


async def test_hot_web_pagination_and_badge_over_100(session_factory):
    ids = await _many_hot(session_factory)
    app = build_web_app(
        Settings(_env_file=None, web_auth_enabled=False, web_manager_id=1001,
                 instagram_provider="mock", openai_api_key="", openai_live_enabled=False),
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(FakeMonitor()), ExternalUsageService(session_factory),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/hot?vertical=FURNITURE&page=4")
        assert page.status_code == 200
        assert "125 лидов в очереди HOT" in page.text
        assert 'aria-label="Страницы очереди HOT"' in page.text
        assert page.text.count('data-hot-lead-id=') == 5
        assert f'&page=4&lead_id={ids[0]}' in page.text
        assert f'data-hot-lead-id="{ids[0]}"' in page.text
        assert (await client.get("/hot?page=9999")).text.count('data-hot-lead-id=') == 5
        assert (await client.get("/hot?page=-1")).text.count('data-hot-lead-id=') == 40
        feed = await client.get("/api/radar/feed?vertical=FURNITURE")
        assert feed.status_code == 200
        assert feed.json()["hot_queue_count"] == 125


async def test_hot_selected_lead_opens_its_actual_queue_page(session_factory):
    ids = await _many_hot(session_factory)
    app = _hot_web_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # A direct link (including the next-client redirect) must select a visible queue item.
        page = await client.get(f"/hot?vertical=FURNITURE&lead_id={ids[0]}")
        assert page.status_code == 200
        assert f'data-hot-lead-id="{ids[0]}"' in page.text
        assert f'&page=4&lead_id={ids[0]}' in page.text
        assert 'data-hot-lead-id="' in page.text
        assert page.text.count('data-hot-lead-id=') == 5
        # A stale page parameter must not leave selection outside the visible queue.
        page = await client.get(f"/hot?page=4&lead_id={ids[-1]}")
        assert page.text.count('data-hot-lead-id=') == 40
        assert f'&page=1&lead_id={ids[-1]}' in page.text


@pytest.mark.parametrize("unavailable", ["missing", "terminal", "stale", "other_vertical"])
async def test_hot_unavailable_selection_falls_back_with_notice(session_factory, unavailable):
    ids = await _many_hot(session_factory, count=3)
    selected_id = ids[-1]
    async with session_factory() as session:
        lead = await session.get(Lead, selected_id)
        if unavailable == "missing":
            selected_id = 999999999
        elif unavailable == "terminal":
            lead.status = LeadStatus.WON
        elif unavailable == "stale":
            (await session.get(Comment, lead.comment_id)).created_at_platform = (
                datetime.now(UTC) - timedelta(days=31)
            )
        else:
            lead.vertical = Vertical.ARTIFICIAL_RATTAN
        await session.commit()
    app = _hot_web_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get(f"/hot?vertical=FURNITURE&lead_id={selected_id}")
        assert page.status_code == 200
        assert "Этот лид уже вне текущей очереди HOT" in page.text
        assert f'ЛИД #{ids[-2] if unavailable != "missing" else ids[-1]}' in page.text
        assert f'ЛИД #{selected_id}' not in page.text


async def test_hot_unavailable_selection_with_empty_queue_is_clear(session_factory):
    app = _hot_web_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        page = await client.get("/hot?lead_id=999999999")
        assert page.status_code == 200
        assert "Сейчас очередь пуста" in page.text
        assert "Пока некому писать" in page.text
        assert 'data-hot-prepare' not in page.text


async def test_hot_prepare_reuses_saved_text_when_gpt_is_off(session_factory):
    ids = await _many_hot(session_factory, count=1)
    saved = await _hot(session_factory).save_draft(ids[0], 1001, "Ручное предложение")
    async with session_factory() as session:
        event_count = await session.scalar(select(func.count(ContactEvent.id)))
    app = _hot_web_app(session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/api/hot/{ids[0]}/prepare", json={})
        assert response.status_code == 200
        assert response.json()["detail"]["draft"] == saved["draft"]
        forced = await client.post(f"/api/hot/{ids[0]}/prepare", json={"force": True})
        assert forced.status_code == 409
        assert "выключен" in forced.json()["detail"]
    async with session_factory() as session:
        assert await session.scalar(select(func.count(ContactEvent.id))) == event_count
    assert await ExternalUsageService(session_factory).used_today("openai") == 0


def _hot_web_app(factory):
    return build_web_app(
        Settings(_env_file=None, web_auth_enabled=False, web_manager_id=1001,
                 instagram_provider="mock", openai_api_key="", openai_live_enabled=False),
        WebQueryService(factory, hot_threshold=70),
        LeadWorkflowService(factory, hot_threshold=70),
        MonitorController(FakeMonitor()), ExternalUsageService(factory),
    )
