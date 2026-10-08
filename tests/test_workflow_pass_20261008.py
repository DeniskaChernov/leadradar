"""Offline regressions for retry-safe CRM, complete history and stalled cursors."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import func, insert, select, update

from app.db.models import (
    Comment,
    Competitor,
    Contact,
    ContactEvent,
    ContactEventType,
    ExternalUsage,
    Lead,
    Post,
    Vertical,
)
from app.providers.budgeted import BudgetedInstagramProvider, ScanBudget
from app.providers.scrapecreators import ScrapeCreatorsProvider
from app.services.crm_service import CRMRequestConflictError, CRMService
from app.services.lead_workflow_service import (
    LeadAlreadyAssignedError,
    LeadWorkflowError,
    LeadWorkflowService,
)
from app.services.usage_service import ExternalUsageService
from app.web.queries import WebQueryService
from tests.conftest import seed_scrapecreators_instagram_policy
from tests.test_comment_capture_reliability import _comment_payload, _monitor, _post
from tests.test_lead_workflow import create_lead
from tests.test_qa_smoke_pages import _app
from tests.test_system_pass_20261008 import _Page


async def _contact(factory):
    lead_id = await create_lead(factory)
    async with factory() as session:
        return lead_id, (await session.get(Lead, lead_id)).contact_id


@pytest.mark.parametrize("kind", ["note", "reply", "reply_without_lead"])
@pytest.mark.parametrize("explicit_key", [True, False])
async def test_concurrent_append_retries_commit_one_event(file_session_factory, kind, explicit_key):
    factory = file_session_factory
    lead_id, contact_id = await _contact(factory)
    crm = CRMService(factory)
    key = {"request_id": "retry-1"} if explicit_key else {}

    async def save():
        if kind == "note":
            return await crm.add_note(contact_id, 1001, "  A note  ", **key)
        return await crm.record_customer_reply(
            contact_id, 1001, text="Reply", lead_id=lead_id if kind == "reply" else None, **key,
        )

    saved = await asyncio.gather(*(save() for _ in range(4)))
    assert len({event.id for event in saved}) == 1
    async with factory() as session:
        before = (await session.get(Contact, contact_id)).last_contacted_at
        event_snapshot = dict((await session.get(ContactEvent, saved[0].id)).payload_json)
    assert (await save()).id == saved[0].id
    async with factory() as session:
        assert (await session.get(Contact, contact_id)).last_contacted_at == before
        assert (await session.get(ContactEvent, saved[0].id)).payload_json == event_snapshot
        event_type = ContactEventType.NOTE_ADDED if kind == "note" else ContactEventType.CUSTOMER_REPLIED
        assert await session.scalar(select(func.count()).select_from(ContactEvent).where(ContactEvent.event_type == event_type)) == 1


@pytest.mark.parametrize("kind", ["note", "reply"])
async def test_explicit_new_key_allows_same_text_but_changed_payload_conflicts(session_factory, kind):
    _lead_id, contact_id = await _contact(session_factory)
    crm = CRMService(session_factory)

    async def save(text, key):
        if kind == "note":
            return await crm.add_note(contact_id, 1001, text, request_id=key)
        return await crm.record_customer_reply(contact_id, 1001, text=text, request_id=key)

    first = await save("Same text", "first")
    assert (await save(" Same text ", "first")).id == first.id
    second = await save("Same text", "second")
    assert second.id != first.id
    with pytest.raises(CRMRequestConflictError):
        await save("Changed text", "first")
    async with session_factory() as session:
        assert (await session.get(ContactEvent, first.id)).payload_json["text"] == "Same text"


async def test_operation_key_scoped_to_manager_contact_and_event_type(session_factory):
    _lead_id, contact_id = await _contact(session_factory)
    second_lead = await create_lead(session_factory, "second", "second-user")
    async with session_factory() as session:
        second_contact = (await session.get(Lead, second_lead)).contact_id
    crm = CRMService(session_factory)
    events = [
        await crm.add_note(contact_id, 1001, "Text", request_id="shared"),
        await crm.add_note(contact_id, 2002, "Text", request_id="shared"),
        await crm.add_note(second_contact, 1001, "Text", request_id="shared"),
        await crm.record_customer_reply(contact_id, 1001, text="Text", request_id="shared"),
    ]
    assert len({event.id for event in events}) == 4


async def test_reply_lead_and_owner_validated_without_side_effects(session_factory):
    lead_id, contact_id = await _contact(session_factory)
    other_lead = await create_lead(session_factory, "other", "other-user")
    crm = CRMService(session_factory)
    with pytest.raises(LeadWorkflowError, match="принадлежит"):
        await crm.record_customer_reply(contact_id, 1001, lead_id=other_lead)
    await LeadWorkflowService(session_factory, 70).assign_manager(lead_id, 2002)
    with pytest.raises(LeadAlreadyAssignedError):
        await crm.record_customer_reply(contact_id, 1001, lead_id=lead_id)
    async with session_factory() as session:
        assert (await session.get(Contact, contact_id)).last_contacted_at is None
        assert await session.scalar(select(func.count()).select_from(ContactEvent).where(ContactEvent.event_type == ContactEventType.CUSTOMER_REPLIED)) == 0


async def test_reply_event_failure_rolls_back_contact_timestamp(session_factory, monkeypatch):
    _lead_id, contact_id = await _contact(session_factory)

    async def fail(*args, **kwargs):
        raise RuntimeError("Simulated database failure")

    monkeypatch.setattr("app.services.crm_service.ContactEventRepository.add", fail)
    with pytest.raises(RuntimeError):
        await CRMService(session_factory).record_customer_reply(contact_id, 1001, request_id="rollback")
    async with session_factory() as session:
        assert (await session.get(Contact, contact_id)).last_contacted_at is None


async def test_committed_reply_retry_survives_later_reassignment(session_factory):
    lead_id, contact_id = await _contact(session_factory)
    crm = CRMService(session_factory)
    first = await crm.record_customer_reply(contact_id, 1001, lead_id=lead_id, text="Reply", request_id="receipt")
    await LeadWorkflowService(session_factory, 70).assign_manager(lead_id, 2002, reassign=True)
    retry = await crm.record_customer_reply(contact_id, 1001, lead_id=lead_id, text="Reply", request_id="receipt")
    assert retry.id == first.id
    with pytest.raises(LeadAlreadyAssignedError):
        await crm.record_customer_reply(contact_id, 1001, lead_id=lead_id, text="Reply", request_id="new-action")


@pytest.mark.parametrize("endpoint", ["notes", "reply"])
async def test_api_retries_return_event_id_and_conflicts_are_409(session_factory, endpoint):
    _lead_id, contact_id = await _contact(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        url = f"/api/contacts/{contact_id}/{endpoint}"
        first = await client.post(url, json={"text": "Text"}, headers={"Idempotency-Key": "api-1"})
        retry = await client.post(url, json={"text": "Text"}, headers={"Idempotency-Key": "api-1"})
        conflict = await client.post(url, json={"text": "Other"}, headers={"Idempotency-Key": "api-1"})
        mismatch = await client.post(url, json={"text": "Text", "request_id": "body"}, headers={"Idempotency-Key": "header"})
    assert first.status_code == retry.status_code == 200
    assert first.json()["event_id"] == retry.json()["event_id"]
    assert conflict.status_code == 409 and mismatch.status_code == 400


@pytest.mark.parametrize("key", ["", "x" * 129, "нельзя", 1, True, [], {}])
async def test_invalid_operation_key_returns_400(session_factory, key):
    _lead_id, contact_id = await _contact(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.post(f"/api/contacts/{contact_id}/notes", json={"text": "Text", "request_id": key})
    assert response.status_code == 400


async def _long_history(factory):
    lead_id, contact_id = await _contact(factory)
    now = datetime.now(UTC)
    async with factory() as session:
        comment = dict((await session.execute(select(Comment.__table__))).mappings().one())
        lead = dict((await session.execute(select(Lead.__table__))).mappings().one())
        post = dict((await session.execute(select(Post.__table__))).mappings().one())
        source = dict((await session.execute(select(Competitor.__table__))).mappings().one())
        await session.execute(insert(Competitor), [{**source, "id": 2, "business_id": None, "handle": "older-source", "normalized_handle": "older-source"}])
        await session.execute(insert(Post), [{**post, "id": 2, "competitor_id": 2, "platform_post_id": "older-post", "url": "https://www.instagram.com/p/older-post/"}])
        await session.execute(insert(Comment), [
            {**comment, "id": i, "platform_comment_id": f"history-{i}", "competitor_id": 2 if i == 2 else source["id"], "post_id": 2 if i == 2 else post["id"], "created_at_platform": None, "discovered_at": now}
            for i in range(2, 174)
        ])
        await session.execute(insert(Lead), [
            {**lead, "id": i, "comment_id": i, "competitor_id": 2 if i == 2 else source["id"], "vertical": Vertical.ARTIFICIAL_RATTAN if i == 3 else Vertical.FURNITURE, "analysis_details": {"commercial_quality": "COMMERCIAL"}}
            for i in range(2, 174)
        ])
        await session.execute(update(Lead).where(Lead.id == lead_id).values(analysis_details={"commercial_quality": "COMMERCIAL"}))
        await session.execute(insert(ContactEvent), [
            {"contact_id": contact_id, "event_type": ContactEventType.CUSTOMER_REPLIED, "payload_json": {"text": f"Reply {i}"}, "created_at": now}
            for i in range(173)
        ] + [
            {"contact_id": contact_id, "event_type": ContactEventType.NOTE_ADDED, "payload_json": {"text": f"Old note {i}"}, "created_at": datetime(2000, 1, 1, tzinfo=UTC)}
            for i in range(12)
        ])
        await session.commit()
    return lead_id, contact_id


@pytest.mark.parametrize("kind", ["signals", "events", "notes", "lead_history"])
async def test_full_detail_history_reachable_stable_and_clamped(session_factory, kind):
    lead_id, contact_id = await _long_history(session_factory)
    queries = WebQueryService(session_factory, 70)

    async def get(page):
        if kind == "lead_history":
            return (await queries.lead_detail(lead_id, history_page=page))["history_pagination"]
        return (await queries.contact_detail(contact_id, **{kind + "_page": page}))[kind + "_pagination"]

    first = await get(1)
    ids = []
    for page in range(1, first.pages + 1):
        result = await get(page)
        ids.extend((row[0] if kind in {"signals", "lead_history"} else row).id for row in result.rows)
    assert len(ids) == len(set(ids)) == first.total
    assert first.total == (173 if kind in {"signals", "lead_history"} else 12 if kind == "notes" else 188)
    assert (await get(-1)).page == 1 and (await get(9999)).page == first.pages
    assert [row.id if kind in {"events", "notes"} else row[0].id for row in (await get(1)).rows] == ids[:first.page_size]


async def test_detail_totals_and_recommendation_do_not_depend_on_page_or_other_vertical(session_factory):
    lead_id, contact_id = await _long_history(session_factory)
    queries = WebQueryService(session_factory, 70)
    for page in (1, 2, 9999):
        data = await queries.lead_detail(lead_id, history_page=page)
        assert data["commercial_competitor_count"] == 2
        data = await queries.contact_detail(contact_id, signals_page=page, events_page=page)
        assert data["source_count"] == 2 and data["signals_pagination"].total == 173
    # The rattan lead shares a contact but has only one rattan commercial source.
    assert (await queries.lead_detail(3))["commercial_competitor_count"] == 1


async def test_detail_pagers_preserve_other_sections_and_anchor(session_factory):
    lead_id, contact_id = await _long_history(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        contact = await client.get(f"/contacts/{contact_id}?signals_page=2&events_page=2&notes_page=2&vertical=ARTIFICIAL_RATTAN")
        lead = await client.get(f"/leads/{lead_id}?history_page=2&vertical=FURNITURE")
    assert contact.status_code == lead.status_code == 200
    page = _Page(contact.text)
    for kind in ("signals", "events", "notes"):
        label = {"signals": "Страницы истории интереса", "events": "Страницы CRM-истории", "notes": "Страницы заметок"}[kind]
        nav = next(node for node in page.nodes if node.tag == "nav" and node.attrs.get("aria-label") == label)
        links = next(node for node in nav.children if hasattr(node, "tag") and node.tag == "div").children
        links = [node for node in links if hasattr(node, "tag") and node.tag == "a"]
        assert links
        for node in links:
            target = urlsplit(node["href"])
            params = parse_qs(target.query)
            assert target.fragment == "contact-" + kind
            assert params["vertical"] == ["ARTIFICIAL_RATTAN"]
            for other in {"signals", "events", "notes"} - {kind}:
                assert params[other + "_page"] == ["2"]
    assert "Old note 0" in contact.text and "Old note 1" in contact.text
    assert 'id="interest-history" open' in lead.text


@pytest.mark.parametrize("field,value", [
    ("budget_from", "NaN"), ("budget_to", "Infinity"), ("budget_from", "-Infinity"),
    ("budget_to", "1e400"), ("desired_quantity", True), ("desired_quantity", 1.5),
    ("desired_quantity", 2**100), ("desired_quantity", 2**31),
])
async def test_bad_qualification_numbers_rejected_without_data_change(session_factory, field, value):
    _lead_id, contact_id = await _contact(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.post(f"/api/contacts/{contact_id}/qualification", json={field: value})
    assert response.status_code == 400
    async with session_factory() as session:
        contact = await session.get(Contact, contact_id)
        assert contact.budget_from is contact.budget_to is contact.desired_quantity is None


@pytest.mark.parametrize("budget", ["100", "100.001", "0"])
async def test_parallel_qualification_retries_do_not_fake_updates(file_session_factory, budget):
    factory = file_session_factory
    _lead_id, contact_id = await _contact(factory)
    crm = CRMService(factory)

    async def save(value):
        return await crm.update_contact_qualification(contact_id, 1001, budget_from=Decimal(value), desired_quantity=2)

    await asyncio.gather(*(save(budget) for _ in range(4)))
    async with factory() as session:
        first = (await session.get(Contact, contact_id)).qualification_updated_at
    expected = Decimal(budget).quantize(Decimal("0.01"))
    await save(str(expected))
    async with factory() as session:
        contact = await session.get(Contact, contact_id)
        assert contact.budget_from == expected and contact.qualification_updated_at == first
        assert await session.scalar(select(func.count()).select_from(ContactEvent).where(ContactEvent.event_type == ContactEventType.QUALIFICATION_UPDATED)) == 1
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(factory)), base_url="http://test") as client:
        response = await client.get(f"/contacts/{contact_id}")
    field = next(node for node in _Page(response.text).nodes if node.tag == "input" and node.attrs.get("name") == "budget_from")
    assert field["value"] == str(expected)


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", "1e400"])
async def test_nonfinite_or_oversized_money_rejected_in_services(session_factory, amount):
    lead_id, contact_id = await _contact(session_factory)
    crm = CRMService(session_factory)
    with pytest.raises(LeadWorkflowError):
        await crm.update_contact_qualification(contact_id, 1001, budget_from=Decimal(amount))
    with pytest.raises(LeadWorkflowError):
        await crm.upsert_deal(lead_id, 1001, amount=Decimal(amount))
    deal = await crm.upsert_deal(lead_id, 1001, amount=Decimal("100"))
    with pytest.raises(LeadWorkflowError):
        await LeadWorkflowService(session_factory, 70).win_deal(deal.id, 1001, product_name="Chair", quantity=1, amount=Decimal(amount))


async def test_zero_sale_quantity_rejected_without_closing_deal(session_factory):
    lead_id, _contact_id = await _contact(session_factory)
    deal = await CRMService(session_factory).upsert_deal(lead_id, 1001, amount=Decimal("100"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.post(f"/api/deals/{deal.id}/win", json={"amount": "100", "quantity": 0, "product_name": "Chair"})
    assert response.status_code == 400
    async with session_factory() as session:
        from app.db.models import Deal, DealSaleSnapshot

        assert (await session.get(Deal, deal.id)).status.value == "NEW"
        assert await session.scalar(select(func.count()).select_from(DealSaleSnapshot)) == 0


@pytest.mark.parametrize("lead_id", [True, 1.5, 2**100, -1])
async def test_invalid_lead_identifier_is_not_truncated_or_bound_to_sqlite(session_factory, lead_id):
    _lead_id, contact_id = await _contact(session_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.post(f"/api/contacts/{contact_id}/reply", json={"lead_id": lead_id})
    assert response.status_code == 400


@pytest.mark.parametrize("budgeted", [False, True])
@pytest.mark.parametrize("start_cursor,cycle", [("a", {"a": "a"}), (None, {None: "a", "a": "b", "b": "a"})])
async def test_cyclic_comment_cursor_keeps_progress_comments_and_cost_truth(session_factory, budgeted, start_cursor, cycle):
    await seed_scrapecreators_instagram_policy(session_factory)
    cursors = []

    def respond(request):
        current = request.url.params.get("cursor")
        cursors.append(current)
        return httpx.Response(200, json={"comments": [_comment_payload(str(current))], "cursor": cycle[current], "credits_charged": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = ScrapeCreatorsProvider("test", client=client, max_comment_pages=10)
        if budgeted:
            provider = BudgetedInstagramProvider(provider, ExternalUsageService(session_factory), enabled=True, daily_limit=100, scan_budget=ScanBudget(default_limit=5))
        batch = await provider.get_comment_batch(_post(), cursor=start_cursor, max_pages=10)
    assert cursors == (["a"] if start_cursor else [None, "a", "b"])
    assert batch.fetch_error == "RepeatedCommentCursor" and batch.coverage_status == "PARTIAL"
    assert not batch.cursor_exhausted and batch.next_cursor == ("a" if start_cursor else "b")
    assert len(batch.comments) == len(cursors) and batch.pages_fetched == len(cursors)
    if budgeted:
        async with session_factory() as session:
            usage = list(await session.scalars(select(ExternalUsage).order_by(ExternalUsage.id)))
            assert len(usage) == len(cursors) and sum(row.units for row in usage) == len(cursors)
            assert not usage[-1].success


async def test_stalled_page_ingested_and_cursor_remains_retryable(session_factory):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
        "comments": [_comment_payload("new-public")], "cursor": "stalled",
    }))) as client:
        provider = ScrapeCreatorsProvider("test", client=client)
        monitor = _monitor(session_factory, provider)
        check = await monitor._prepare_post(_post())
        # Simulate a persisted backfill position from an earlier scan.
        check = replace(check, comment_cursor="stalled", is_backfill=True)
        from app.services.instagram_monitor import CycleStats

        stats = CycleStats()
        await monitor._process_prepared_reel(_post(), check, stats)
        async with session_factory() as session:
            post = await session.scalar(select(Post))
            assert post.comment_backfill_cursor == "stalled" and post.coverage_status.value == "PARTIAL"
            assert await session.scalar(select(func.count()).select_from(Comment)) == 1
        assert stats.errors == 1
