"""Contact outreach links use the same eligibility and ordering as the HOT queue."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.db.models import Comment, ContactEvent, ContactTask, Lead, LeadStatus, Vertical
from tests.e2e.helpers import build_e2e_app
from tests.test_hot_backend_reliability import _service
from tests.test_openings_and_hot_pagination import _many_hot


@pytest.mark.parametrize('reason', ['low_score', 'excluded', 'review', 'stale', 'negotiation', 'sent', 'lost'])
async def test_contact_has_no_outreach_link_for_leads_outside_hot(session_factory, reason):
    lead_id = (await _many_hot(session_factory, 1))[0]
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        contact_id = lead.contact_id
        if reason == 'low_score':
            lead.lead_score = 69
        elif reason in {'excluded', 'review'}:
            lead.analysis_details = {'assortment': {'status': reason.upper()}}
        elif reason == 'stale':
            comment = await session.get(Comment, lead.comment_id)
            comment.created_at_platform = datetime.now(UTC) - timedelta(days=31)
        else:
            lead.status = {'negotiation': LeadStatus.NEGOTIATION,
                           'sent': LeadStatus.OFFER_SENT, 'lost': LeadStatus.LOST}[reason]
        session.add(ContactTask(contact_id=contact_id, lead_id=lead_id,
                                due_at=datetime.now(UTC) + timedelta(hours=1), note='target-regression-task'))
        await session.commit()
        history_before = await session.scalar(select(func.count()).select_from(ContactEvent))
    async with AsyncClient(transport=ASGITransport(app=build_e2e_app(session_factory)),
                           base_url='http://testserver') as client:
        response = await client.get(f'/contacts/{contact_id}')
        detail = await client.get(f'/leads/{lead_id}')
        radar = await client.get('/radar')
        other_pages = [await client.get(path) for path in ('/', '/leads?view=list', '/leads?view=board', '/tasks')]
    assert response.status_code == 200
    assert f'/leads/{lead_id}' in response.text  # History remains readable.
    assert '>Написать</a>' not in response.text
    assert detail.status_code == radar.status_code == 200
    assert f'/hot?vertical=FURNITURE&lead_id={lead_id}' not in detail.text
    assert f'/hot?vertical=FURNITURE&lead_id={lead_id}' not in radar.text
    for page in other_pages:
        assert page.status_code == 200
        assert f'/hot?vertical=FURNITURE&lead_id={lead_id}' not in page.text
    assert 'target-regression-task' in other_pages[-1].text
    if reason in {'negotiation', 'sent', 'lost'}:
        assert f'data-lead-take="{lead_id}"' not in radar.text
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ContactEvent)) == history_before


async def test_contact_outreach_target_matches_full_queue_order_and_vertical(session_factory):
    ids = await _many_hot(session_factory, 3)
    async with session_factory() as session:
        leads = [await session.get(Lead, lead_id) for lead_id in ids]
        contact_id = leads[0].contact_id
        for lead in leads[:2]:
            lead.contact_id = contact_id
            (await session.get(Comment, lead.comment_id)).contact_id = contact_id
        leads[0].lead_score = 80
        leads[1].lead_score = 96
        leads[1].vertical = Vertical.ARTIFICIAL_RATTAN
        leads[2].lead_score = 99  # Another contact must never win this choice.
        await session.commit()
    service = _service(session_factory)
    expected = next(item for item in await service.queue() if item['lead_id'] in ids[:2])
    target = await service.contact_target(contact_id)
    assert target == {'lead_id': expected['lead_id'], 'vertical': 'ARTIFICIAL_RATTAN'}
    assert await service.contact_target(999999) is None
    async with AsyncClient(transport=ASGITransport(app=build_e2e_app(session_factory)),
                           base_url='http://testserver') as client:
        response = await client.get(f'/contacts/{contact_id}')
    assert f'/hot?vertical=ARTIFICIAL_RATTAN&lead_id={ids[1]}' in response.text


async def test_contact_target_skips_ineligible_higher_score_and_keeps_history(session_factory):
    ids = await _many_hot(session_factory, 2)
    async with session_factory() as session:
        first, second = [await session.get(Lead, lead_id) for lead_id in ids]
        contact_id = first.contact_id
        first.lead_score = 100
        first.analysis_details = {'assortment': {'status': 'EXCLUDED'}}
        second.contact_id = contact_id
        (await session.get(Comment, second.comment_id)).contact_id = contact_id
        await session.commit()
    assert (await _service(session_factory).contact_target(contact_id))['lead_id'] == ids[1]
    async with AsyncClient(transport=ASGITransport(app=build_e2e_app(session_factory)),
                           base_url='http://testserver') as client:
        response = await client.get(f'/contacts/{contact_id}')
    assert f'/hot?vertical=FURNITURE&lead_id={ids[1]}' in response.text
    assert all(f'/leads/{lead_id}' in response.text for lead_id in ids)
