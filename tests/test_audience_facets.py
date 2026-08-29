from datetime import UTC, datetime, timedelta

from app.db.models import AudienceMembership, Contact, ContactIntelligence
from app.services.audience_facet_service import AudienceFacetQuery


def _rows():
    membership = AudienceMembership(segment_id=1, contact_id=1, confidence=82)
    contact = Contact(
        platform="instagram",
        username="buyer",
        normalized_username="buyer",
        profile_url="https://instagram.com/buyer",
        city="Tashkent",
        assigned_manager_telegram_id=77,
    )
    intelligence = ContactIntelligence(
        contact_id=1,
        vertical="FURNITURE",
        commercial_stage="PURCHASE_INTENT",
        quantity_band="50_PLUS",
        primary_buyer_role="B2B_HORECA",
        product_interests_json=[{"value": "CHAIRS"}],
        top_intents_json=[{"value": "QUANTITY"}],
        purchase_horizon="THIS_MONTH",
        value_score=78,
        last_seen_at=datetime.now(UTC) - timedelta(days=3),
    )
    return membership, contact, intelligence


def test_facets_compose_without_creating_audience_definition():
    membership, contact, intelligence = _rows()
    facets = AudienceFacetQuery.from_mapping(
        {
            "product_family": "CHAIRS",
            "intent": "QUANTITY",
            "buyer_role": "B2B_HORECA",
            "city": "tashkent",
            "confidence_band": "HIGH",
            "value_band": "HIGH",
            "recency_bucket": "0_7",
            "source_competitor": "aiko.uz",
            "manager_status": "ASSIGNED",
            "won_status": "WON",
        }
    )

    assert facets.matches(
        membership,
        contact,
        intelligence,
        source_competitors={"aiko.uz"},
        won_statuses={"WON"},
    )
    assert len(facets.active) == 10


def test_one_mismatching_facet_excludes_member():
    membership, contact, intelligence = _rows()
    facets = AudienceFacetQuery(product_family="TABLE")

    assert not facets.matches(membership, contact, intelligence)


def test_rattan_facets_are_independent_and_composable():
    membership, contact, intelligence = _rows()
    facets = AudienceFacetQuery(rattan_layer="RAW_MATERIAL", rattan_role="RAW_BUYER")

    assert facets.matches(
        membership,
        contact,
        intelligence,
        rattan_layers={"RAW_MATERIAL"},
        rattan_roles={"RAW_BUYER"},
    )
    assert not facets.matches(
        membership,
        contact,
        intelligence,
        rattan_layers={"READY_FURNITURE"},
        rattan_roles={"RAW_BUYER"},
    )
