"""Display saved confidence consistently without changing assessments or contacting providers."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.models import Lead, Vertical
from app.web.lead_ui_helpers import confidence_percent, lead_confidence
from app.web.queries import WebQueryService
from tests.e2e.helpers import build_e2e_app
from tests.test_hot_backend_reliability import _service
from tests.test_openings_and_hot_pagination import _many_hot


@pytest.mark.parametrize(('value', 'expected'), [
    (85, 85), (0, 0), (1, 1), (100, 100), (0.85, 85), (1.0, 100),
    ('0.85', 85), ('1', 1), ('1.0', 100), ('85', 85), (' 85.5 ', 86),
    (Decimal('0.85'), 85), (None, None), (True, None), (False, None),
    ('', None), ('unknown', None), ('NaN', None), ('Infinity', None),
    (float('nan'), None), (float('inf'), None), (-1, None), (101, None), ({}, None),
])
def test_confidence_formats_are_explicit(value, expected):
    assert confidence_percent(value) == expected


@pytest.mark.parametrize(('details', 'expected'), [
    ({}, None), ({'confidence': None, 'confidence_score': 85}, 85),
    ({'factors': {'confidence_score': 0.85}}, 85),
    ({'confidence': 0, 'confidence_score': 85}, 0),
    ({'confidence': 'bad', 'confidence_score': 85}, None),
])
def test_confidence_does_not_invent_fifty_or_replace_zero(details, expected):
    assert lead_confidence(SimpleNamespace(analysis_details=details)) == expected


@pytest.mark.parametrize(('saved', 'expected'), [(0.85, 85), ('0.85', 85), (1, 1), (0, 0), (None, None)])
async def test_api_and_both_templates_use_the_same_confidence(session_factory, saved, expected):
    lead_id = (await _many_hot(session_factory, 1))[0]
    async with session_factory() as session:
        lead = await session.get(Lead, lead_id)
        original = {'buyer_role': 'B2C_CONSUMER', 'confidence': saved,
                    'factors': {'confidence_score': saved}}
        lead.analysis_details = original
        await session.commit()
    explanation = await WebQueryService(session_factory, 70).lead_explain(lead_id)
    assert explanation['confidence'] == expected
    assert explanation['buyer_role_label'] == 'Розничный покупатель'
    if expected:
        assert any(row['key'] == 'confidence_score' and row['score'] == expected
                   for row in explanation['contributions'])
    async with AsyncClient(transport=ASGITransport(app=build_e2e_app(session_factory)),
                           base_url='http://testserver') as client:
        detail = await client.get(f'/leads/{lead_id}')
        radar = await client.get('/radar')
    assert detail.status_code == radar.status_code == 200
    expected_label = f'Уверенность {expected}%' if expected is not None else 'Уверенность не сохранена'
    assert expected_label in detail.text
    if expected is not None:
        assert expected_label in radar.text
    assert 'Розничный покупатель' in radar.text and '>B2C_CONSUMER<' not in radar.text
    assert f'/hot?vertical=FURNITURE&lead_id={lead_id}' in detail.text
    assert f'/hot?vertical=FURNITURE&lead_id={lead_id}' in radar.text
    async with session_factory() as session:
        assert (await session.get(Lead, lead_id)).analysis_details == original


async def test_hot_membership_is_batched_and_scoped_to_requested_ids_and_vertical(session_factory):
    ids = await _many_hot(session_factory, 3)
    async with session_factory() as session:
        (await session.get(Lead, ids[1])).analysis_details = {'assortment': {'status': 'REVIEW'}}
        (await session.get(Lead, ids[2])).vertical = Vertical.ARTIFICIAL_RATTAN
        await session.commit()
    service = _service(session_factory)
    assert await service.queued_lead_ids([]) == set()
    assert await service.queued_lead_ids(ids[:2]) == {ids[0]}
    assert await service.queued_lead_ids(ids, vertical='FURNITURE') == {ids[0]}
    assert await service.queued_lead_ids(ids, vertical='ARTIFICIAL_RATTAN') == {ids[2]}
