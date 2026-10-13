"""Cross-system regression scenarios; all mutations use disposable SQLite databases."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, insert, select

from app.db.models import (
    Comment,
    Contact,
    ContactEvent,
    ContactEventType,
    ContactTask,
    Deal,
    DealStatus,
    Lead,
    TaskStatus,
    Vertical,
)
from app.services.crm_service import CRMService
from app.services.lead_workflow_service import LeadAlreadyAssignedError, LeadWorkflowService
from app.web.queries import WebQueryService
from tests.test_lead_workflow import create_lead
from tests.test_qa_smoke_pages import _app


class _Node:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []

    def __getitem__(self, key):
        return self.attrs[key]

    def get_text(self, separator=" ", strip=True):
        parts = [child.get_text(separator, strip) if isinstance(child, _Node) else child for child in self.children]
        return separator.join(part.strip() if strip else part for part in parts)


class _Page(HTMLParser):
    """Inspect actual rendered markup without adding a parsing dependency."""

    def __init__(self, html):
        super().__init__()
        self.root = _Node("root", {})
        self.stack = [self.root]
        self.nodes = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        self.nodes.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def select_one(self, selector):
        if selector.startswith("."):
            return next((node for node in self.nodes if selector[1:] in node.attrs.get("class", "").split()), None)
        return next((node for node in self.nodes if node.tag == "a" and node.attrs.get("rel") == "next"), None)

    def find(self, tag, *, string):
        return next((node for node in self.nodes if node.tag == tag and node.get_text().strip() == string), None)


async def _seed_rows(factory, count):
    await create_lead(factory)
    async with factory() as session:
        contact = dict((await session.execute(select(Contact.__table__))).mappings().one())
        comment = dict((await session.execute(select(Comment.__table__))).mappings().one())
        lead = dict((await session.execute(select(Lead.__table__))).mappings().one())
        now = datetime.now(UTC)
        await session.execute(insert(Contact), [
            {**contact, "id": i, "platform_user_id": f"page-user-{i}", "username": f"page-user-{i:04d}", "normalized_username": f"page-user-{i:04d}", "last_seen_at": now}
            for i in range(2, count + 1)
        ])
        await session.execute(insert(Comment), [
            {**comment, "id": i, "contact_id": i, "platform_comment_id": f"page-comment-{i}", "discovered_at": now}
            for i in range(2, count + 1)
        ])
        await session.execute(insert(Lead), [
            {**lead, "id": i, "contact_id": i, "comment_id": i, "created_at": now}
            for i in range(2, count + 1)
        ])
        await session.execute(insert(ContactTask), [
            {"id": i, "contact_id": i, "lead_id": i, "manager_telegram_id": 1001, "due_at": now + timedelta(days=1), "note": "Follow up", "status": TaskStatus.OPEN}
            for i in range(1, count + 1)
        ])
        await session.execute(insert(Deal), [
            {"id": i, "lead_id": i, "contact_id": i, "manager_telegram_id": 1001, "status": DealStatus.NEW, "amount": Decimal("1200"), "product_name": "Chair", "created_at": now, "updated_at": now}
            for i in range(1, count + 1)
        ])
        await session.commit()


@pytest.mark.parametrize("name", ["leads", "signals", "contacts", "tasks", "deals"])
async def test_every_record_remains_reachable_after_300_rows(session_factory, name):
    await _seed_rows(session_factory, 331)
    queries = WebQueryService(session_factory, 70)
    ids = []
    for number in range(1, 8):
        result = await getattr(queries, name + "_page")(page=number)
        assert result.total == 331 and result.pages == 7 and result.page == number
        assert len(result.rows) == (50 if number < 7 else 31)
        ids.extend(row[0].id for row in result.rows)
    assert len(ids) == len(set(ids)) == 331
    assert set(ids) == set(range(1, 332))
    repeated = await getattr(queries, name + "_page")(page=2)
    assert [row[0].id for row in repeated.rows] == ids[50:100]
    assert (await getattr(queries, name + "_page")(page=-5)).page == 1
    assert (await getattr(queries, name + "_page")(page=9999)).page == 7
    empty = await getattr(queries, name + "_page")(q="no-such-record", page=9999)
    assert empty.total == 0 and empty.rows == [] and empty.start == empty.end == 0


@pytest.mark.parametrize("path", [
    "/radar?kind=hot&competitor=competitor&vertical=FURNITURE",
    "/leads?view=list&status=NEW&vertical=FURNITURE",
    "/contacts?q=page-user",
    "/tasks?view=open&q=Follow",
    "/deals?status=NEW&q=Chair",
])
async def test_pagination_links_preserve_active_filters(session_factory, path):
    await _seed_rows(session_factory, 105)
    # The source constraint is meaningful: use the actual fixture's handle.
    if path.startswith("/radar"):
        queries = WebQueryService(session_factory, 70)
        row = (await queries.leads(limit=1))[0]
        handle = row[3].normalized_handle
        path = path.replace("competitor=competitor", "competitor=" + handle)
        # The grouped overview has one publication; its full comments view is paginated.
        path += "&post=" + str(row[2].post_id)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get(path)
        assert response.status_code == 200
        page = _Page(response.text)
        link = page.select_one('[data-list-pagination] a[rel="next"]')
        assert link, response.text[-1200:]
        params = parse_qs(urlsplit(link["href"]).query)
        assert params == {**parse_qs(urlsplit(path).query), "page": ["2"]}
        following = await client.get(link["href"])
        assert following.status_code == 200
        assert "Страница 2 из 3" in following.text
        if path.startswith("/leads"):
            assert 'data-operator-board' not in response.text
            assert response.text.count('<article class="lead-card ') == 50


async def test_csv_streams_all_rows_beyond_1000_and_keeps_filters(session_factory):
    await _seed_rows(session_factory, 1007)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get("/api/leads/export.csv?status=NEW&vertical=FURNITURE")
        assert response.status_code == 200
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert len(rows) == 1007
        assert {int(row["lead_id"]) for row in rows} == set(range(1, 1008))
        filtered = await client.get("/api/leads/export.csv?q=page-user-1007&status=NEW")
        assert len(list(csv.DictReader(io.StringIO(filtered.text)))) == 1
        invalid = await client.get("/api/leads/export.csv?status=unknown")
        assert list(csv.DictReader(io.StringIO(invalid.text))) == []


@pytest.mark.parametrize("quality", ["off_catalog", "garbage"])
async def test_suspicious_filter_supports_cyrillic_json_on_sqlite(session_factory, quality):
    lead_id = await create_lead(session_factory)
    await create_lead(session_factory, "comment-2", "user-2")
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        lead.analysis_details = {"risk_flags": ["Не наш ассортимент"]}
        await session.commit()
    result = await WebQueryService(session_factory, 70).leads_page(quality=quality)
    assert [row[0].id for row in result.rows] == [lead_id]
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get("/leads?quality=" + quality)
    assert response.status_code == 200 and "user-1" in response.text


async def _task_context(factory):
    lead_id = await create_lead(factory)
    async with factory() as session:
        lead = await session.get(Lead, lead_id)
        return lead_id, lead.contact_id


@pytest.mark.parametrize("with_lead", [True, False])
@pytest.mark.parametrize("close_method", ["complete_task", "cancel_task"])
async def test_parallel_scheduling_and_retry_after_completion_are_idempotent(file_session_factory, with_lead, close_method):
    lead_id, contact_id = await _task_context(file_session_factory)
    crm = CRMService(file_session_factory)
    arguments = {"due_at": datetime.now(UTC) + timedelta(days=1), "note": " Follow up ", "lead_id": lead_id if with_lead else None}
    tasks = await asyncio.gather(*(crm.schedule_contact(contact_id, 1001, **arguments) for _ in range(4)))
    assert len({task.id for task in tasks}) == 1
    closed = await getattr(crm, close_method)(tasks[0].id, 1001)
    repeated = await crm.schedule_contact(contact_id, 1001, **arguments)
    assert repeated.id == tasks[0].id and repeated.status == closed.status
    async with file_session_factory() as session:
        assert await session.scalar(select(func.count(ContactTask.id))) == 1
        assert await session.scalar(select(func.count(ContactEvent.id)).where(ContactEvent.event_type == ContactEventType.NEXT_CONTACT_SCHEDULED)) == 1


@pytest.mark.parametrize("close_method", ["complete_task", "cancel_task"])
@pytest.mark.parametrize("same_time", [False, True])
async def test_closing_one_task_keeps_next_open_task(session_factory, close_method, same_time):
    lead_id, contact_id = await _task_context(session_factory)
    crm = CRMService(session_factory)
    first_due = datetime.now(UTC) + timedelta(days=1)
    second_due = first_due if same_time else first_due + timedelta(hours=1)
    second = await crm.schedule_contact(contact_id, 1001, due_at=second_due, note="Second", lead_id=lead_id)
    first = await crm.schedule_contact(contact_id, 1001, due_at=first_due, note="First", lead_id=lead_id)
    # Earliest deadline, then stable task ID, is the next actionable contact.
    expected_first = second if same_time else first
    async with session_factory() as session:
        assert (await session.get(Lead, lead_id)).next_action_note == expected_first.note
    await getattr(crm, close_method)(first.id, 1001)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.next_action_note == "Second" and lead.next_action_at is not None
    await getattr(crm, close_method)(second.id, 1001)
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        assert lead.next_action_at is None and lead.next_action_note is None


async def test_task_cannot_be_scheduled_for_another_managers_lead(session_factory):
    lead_id, contact_id = await _task_context(session_factory)
    await LeadWorkflowService(session_factory, 70).assign_manager(lead_id, 1001)
    with pytest.raises(LeadAlreadyAssignedError):
        await CRMService(session_factory).schedule_contact(contact_id, 2002, due_at=datetime.now(UTC), note="Other", lead_id=lead_id)
    async with session_factory() as session:
        assert await session.scalar(select(func.count(ContactTask.id))) == 0


async def test_cancelled_tasks_remain_visible_without_complete_action(session_factory):
    lead_id, contact_id = await _task_context(session_factory)
    crm = CRMService(session_factory)
    task = await crm.schedule_contact(contact_id, 1001, due_at=datetime.now(UTC), note="Cancelled contact", lead_id=lead_id)
    await crm.cancel_task(task.id, 1001)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get("/tasks?view=cancelled")
    assert response.status_code == 200 and "Отменено" in response.text and "Cancelled contact" in response.text
    assert 'data-task-complete=' not in response.text


async def test_rattan_task_links_to_its_own_hot_workspace(session_factory):
    lead_id, contact_id = await _task_context(session_factory)
    async with session_factory() as session:
        (await session.get(Lead, lead_id)).vertical = Vertical.ARTIFICIAL_RATTAN
        await session.commit()
    await CRMService(session_factory).schedule_contact(contact_id, 1001, due_at=datetime.now(UTC), note="Call", lead_id=lead_id)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        response = await client.get("/tasks")
    page = _Page(response.text)
    link = page.find("a", string="Написать")
    assert parse_qs(urlsplit(link["href"]).query) == {"vertical": ["ARTIFICIAL_RATTAN"], "lead_id": [str(lead_id)]}


async def test_sale_currency_is_consistent_in_deals_and_both_detail_pages(session_factory):
    lead_id, contact_id = await _task_context(session_factory)
    workflow = LeadWorkflowService(session_factory, 70)
    await workflow.assign_manager(lead_id, 1001)
    deal = await CRMService(session_factory).upsert_deal(lead_id, 1001, product_name="Chair", amount=Decimal("150"), quantity=1)
    await workflow.win_deal(deal.id, 1001, product_name="Chair", amount=Decimal("100"), quantity=1, sale_currency="USD")
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory)), base_url="http://test") as client:
        for path, selector in [("/deals", ".deal-card-head"), (f"/leads/{lead_id}", ".deal-summary"), (f"/contacts/{contact_id}", ".deal-row")]:
            response = await client.get(path)
            assert response.status_code == 200
            text = _Page(response.text).select_one(selector).get_text(" ", strip=True)
            assert "USD" in text and "сум" not in text and "100" in text


@pytest.mark.parametrize("path,payload", [
    ("/api/contacts/1/tasks", {"due_at": "2026-10-10T12:00", "lead_id": "bad"}),
    ("/api/contacts/1/reply", {"lead_id": "bad", "text": "Reply"}),
])
async def test_invalid_optional_ids_return_user_error(session_factory, path, payload):
    await create_lead(session_factory)
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory), raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post(path, json=payload)
    assert response.status_code == 400


@pytest.mark.parametrize("body", ["{broken", "[1,2]", "null"])
@pytest.mark.parametrize("path", ["/api/contacts/1/notes", "/api/pricing", "/api/pricing/fx", "/api/auth/telegram"])
async def test_bad_json_has_actionable_error_instead_of_500(session_factory, body, path):
    async with AsyncClient(transport=ASGITransport(app=_app(session_factory), raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.post(path, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400 and "JSON" in response.json()["detail"]
