"""Независимые labeled cases для audience membership gate (не используются при калибровке)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class AudienceProfileSpec:
    dimension: str
    topic: str
    commercial_signal_count: int = 1
    current_score: int = 60
    evidence_ids: tuple[int, ...] = (1,)


@dataclass(frozen=True, slots=True)
class AudienceMembershipUnseenCase:
    case_id: str
    facts: dict
    expected: dict[str, bool]
    profiles: tuple[AudienceProfileSpec, ...] = ()
    source_competitors: tuple[int | None, ...] = ()
    source_ages_days: tuple[int, ...] = ()


_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def _base_facts(**overrides: object) -> dict:
    payload = {
        "hot": False,
        "current_intent_score": 65,
        "commercial_signals": 1,
        "recency_days": 10,
        "products": (),
        "intents": (),
        "sources": 1,
        "customer_type": "B2C",
        "quantity": 0,
        "value": 65,
        "reactivated": False,
        "buyer_role": "B2C_CONSUMER",
        "evidence_ids": [1],
        "vertical": "FURNITURE",
        "rattan_layers": set(),
        "rattan_roles": set(),
        "evaluated_at": _NOW,
    }
    payload.update(overrides)
    return payload


AUDIENCE_MEMBERSHIP_UNSEEN_CASES: tuple[AudienceMembershipUnseenCase, ...] = (
    AudienceMembershipUnseenCase(
        "commercial_single_signal",
        _base_facts(),
        {"furniture-commercial-intent": True, "furniture-high-intent": False, "furniture-b2b": False},
    ),
    AudienceMembershipUnseenCase(
        "high_intent_recent",
        _base_facts(current_intent_score=78, recency_days=8, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-high-intent": True, "furniture-commercial-intent": True, "furniture-b2b": False},
    ),
    AudienceMembershipUnseenCase(
        "stale_high_intent",
        _base_facts(current_intent_score=82, recency_days=40),
        {"furniture-high-intent": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "b2b_quantity",
        _base_facts(customer_type="B2B", quantity=40, value=85, buyer_role="B2B_HORECA"),
        {"furniture-b2b": True, "furniture-commercial-intent": True, "furniture-high-intent": False},
    ),
    AudienceMembershipUnseenCase(
        "b2c_not_b2b",
        _base_facts(customer_type="B2C", quantity=6),
        {"furniture-b2b": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "designer_role",
        _base_facts(buyer_role="DESIGNER_CONTRACTOR", current_intent_score=70),
        {"furniture-designers": True, "furniture-b2b": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "comparison_two_sources",
        _base_facts(sources=2, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-comparison": True, "furniture-commercial-intent": True},
        source_competitors=(10, 20),
    ),
    AudienceMembershipUnseenCase(
        "comparison_one_source",
        _base_facts(sources=1, commercial_signals=1),
        {"furniture-comparison": False, "furniture-commercial-intent": True},
        source_competitors=(10,),
    ),
    AudienceMembershipUnseenCase(
        "comparison_stale_source",
        _base_facts(sources=2, commercial_signals=2, recency_days=5, evidence_ids=[1, 2]),
        {"furniture-comparison": False, "furniture-commercial-intent": True},
        source_competitors=(10, 20),
        source_ages_days=(60, 5),
    ),
    AudienceMembershipUnseenCase(
        "reactivated_contact",
        _base_facts(reactivated=True, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-reactivated": True, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "not_reactivated",
        _base_facts(reactivated=False),
        {"furniture-reactivated": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "chairs_product",
        _base_facts(products={"CHAIRS"}, intents={"BUY"}),
        {"furniture-seating": True, "furniture-tables": False, "furniture-commercial-intent": True},
        profiles=(AudienceProfileSpec("PRODUCT", "CHAIRS", 2, 72, (1, 2)),),
    ),
    AudienceMembershipUnseenCase(
        "tables_product",
        _base_facts(products={"TABLE"}),
        {"furniture-tables": True, "furniture-seating": False},
        profiles=(AudienceProfileSpec("PRODUCT", "TABLE", 2, 68, (3,)),),
    ),
    AudienceMembershipUnseenCase(
        "dining_set",
        _base_facts(products={"DINING_SET"}),
        {"furniture-dining": True, "furniture-tables": False},
        profiles=(AudienceProfileSpec("PRODUCT", "DINING_SET", 2, 70, (4,)),),
    ),
    AudienceMembershipUnseenCase(
        "outdoor_product",
        _base_facts(products={"OUTDOOR_FURNITURE"}),
        {"furniture-outdoor": True, "furniture-seating": False},
        profiles=(AudienceProfileSpec("PRODUCT", "OUTDOOR_FURNITURE", 2, 66, (5,)),),
    ),
    AudienceMembershipUnseenCase(
        "furniture_set_family",
        _base_facts(products={"SET"}),
        {"furniture-sets": True, "furniture-dining": False},
        profiles=(AudienceProfileSpec("PRODUCT", "SET", 2, 64, (6,)),),
    ),
    AudienceMembershipUnseenCase(
        "price_intent",
        _base_facts(intents={"PRICE"}),
        {"price-sensitive-research": True, "furniture-commercial-intent": True},
        profiles=(AudienceProfileSpec("INTENT", "PRICE", 2, 60, (7,)),),
    ),
    AudienceMembershipUnseenCase(
        "availability_intent",
        _base_facts(intents={"AVAILABILITY"}),
        {"availability-ready": True, "price-sensitive-research": False},
        profiles=(AudienceProfileSpec("INTENT", "AVAILABILITY", 2, 62, (8,)),),
    ),
    AudienceMembershipUnseenCase(
        "high_intent_threshold_edge",
        _base_facts(current_intent_score=70, recency_days=12, commercial_signals=2, evidence_ids=[1, 2]),
        {
            "furniture-high-intent": True,
            "furniture-commercial-intent": True,
            "logistics-ready": False,
            "catalog-research": False,
        },
    ),
    AudienceMembershipUnseenCase(
        "delivery_intent",
        _base_facts(intents={"DELIVERY"}),
        {"logistics-ready": True, "availability-ready": False, "furniture-commercial-intent": True},
        profiles=(AudienceProfileSpec("INTENT", "DELIVERY", 2, 58, (14,)),),
    ),
    AudienceMembershipUnseenCase(
        "quantity_intent",
        _base_facts(intents={"QUANTITY"}, quantity=12),
        {"bulk-quantity-intent": True, "furniture-b2b": False, "furniture-commercial-intent": True},
        profiles=(AudienceProfileSpec("INTENT", "QUANTITY", 2, 66, (15,)),),
    ),
    AudienceMembershipUnseenCase(
        "catalog_intent",
        _base_facts(intents={"CATALOG"}),
        {"catalog-research": True, "price-sensitive-research": False},
        profiles=(AudienceProfileSpec("INTENT", "CATALOG", 2, 60, (16,)),),
    ),
    AudienceMembershipUnseenCase(
        "rattan_commercial",
        _base_facts(vertical="ARTIFICIAL_RATTAN", commercial_signals=2, evidence_ids=[1, 2]),
        {"rattan-commercial": True, "furniture-commercial-intent": False},
    ),
    AudienceMembershipUnseenCase(
        "rattan_raw_layer_basic",
        _base_facts(vertical="ARTIFICIAL_RATTAN", rattan_layers={"RAW_MATERIAL"}),
        {"rattan-raw-buyers": True, "rattan-ready-furniture-buyers": False},
    ),
    AudienceMembershipUnseenCase(
        "rattan_ready_layer",
        _base_facts(vertical="ARTIFICIAL_RATTAN", rattan_layers={"READY_FURNITURE"}),
        {"rattan-ready-furniture-buyers": True, "rattan-raw-buyers": False},
    ),
    AudienceMembershipUnseenCase(
        "rattan_manufacturer_role",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_layers={"RAW_MATERIAL"},
            rattan_roles={"MANUFACTURER"},
        ),
        {"rattan-manufacturers": True, "rattan-raw-sellers": False},
    ),
    AudienceMembershipUnseenCase(
        "rattan_raw_seller_role",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_layers={"RAW_MATERIAL"},
            rattan_roles={"RAW_RATTAN_RESELLER"},
        ),
        {"rattan-raw-sellers": True, "rattan-manufacturers": False},
    ),
    AudienceMembershipUnseenCase(
        "rattan_import_distribution",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_roles={"IMPORTER"},
            rattan_layers={"RAW_MATERIAL"},
        ),
        {"rattan-import-distribution": True, "rattan-raw-sellers": False},
    ),
    AudienceMembershipUnseenCase(
        "rattan_wholesale_b2b",
        _base_facts(vertical="ARTIFICIAL_RATTAN", customer_type="B2B", buyer_role="B2B_HORECA"),
        {"rattan-wholesale": True, "furniture-b2b": False},
    ),
    AudienceMembershipUnseenCase(
        "multi_product_seating",
        _base_facts(products={"CHAIRS", "SOFA"}),
        {"furniture-seating": True, "furniture-tables": False},
        profiles=(
            AudienceProfileSpec("PRODUCT", "CHAIRS", 2, 70, (11,)),
            AudienceProfileSpec("PRODUCT", "SOFA", 1, 55, (12,)),
        ),
    ),
    AudienceMembershipUnseenCase(
        "intent_buy_profile",
        _base_facts(intents={"BUY"}, current_intent_score=74),
        {"furniture-commercial-intent": True, "furniture-high-intent": True},
        profiles=(AudienceProfileSpec("INTENT", "BUY", 2, 74, (13,)),),
    ),
    AudienceMembershipUnseenCase(
        "low_intent_no_high",
        _base_facts(current_intent_score=62, recency_days=25),
        {"furniture-high-intent": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "comparison_three_sources",
        _base_facts(sources=3, commercial_signals=3, evidence_ids=[1, 2, 3]),
        {"furniture-comparison": True},
        source_competitors=(10, 20, 30),
    ),
    AudienceMembershipUnseenCase(
        "ready_furniture_seller",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_layers={"READY_FURNITURE"},
            rattan_roles={"FURNITURE_RESELLER"},
        ),
        {"rattan-ready-furniture-sellers": True, "rattan-ready-furniture-buyers": True},
    ),
    AudienceMembershipUnseenCase(
        "seating_and_tables_negative",
        _base_facts(products={"CHAIRS"}),
        {"furniture-seating": True, "furniture-tables": False, "furniture-dining": False},
        profiles=(AudienceProfileSpec("PRODUCT", "CHAIRS", 2, 68, (21,)),),
    ),
    AudienceMembershipUnseenCase(
        "dining_and_sets",
        _base_facts(products={"DINING_SET"}),
        {"furniture-dining": True, "furniture-sets": True, "furniture-tables": False},
        profiles=(AudienceProfileSpec("PRODUCT", "DINING_SET", 2, 72, (22,)),),
    ),
    AudienceMembershipUnseenCase(
        "price_not_availability",
        _base_facts(intents={"PRICE"}),
        {"price-sensitive-research": True, "availability-ready": False, "logistics-ready": False},
        profiles=(AudienceProfileSpec("INTENT", "PRICE", 2, 61, (23,)),),
    ),
    AudienceMembershipUnseenCase(
        "availability_not_price",
        _base_facts(intents={"AVAILABILITY"}),
        {"availability-ready": True, "price-sensitive-research": False, "catalog-research": False},
        profiles=(AudienceProfileSpec("INTENT", "AVAILABILITY", 2, 63, (24,)),),
    ),
    AudienceMembershipUnseenCase(
        "b2b_not_designer",
        _base_facts(customer_type="B2B", buyer_role="B2B_HORECA", quantity=25),
        {"furniture-b2b": True, "furniture-designers": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "designer_not_b2b",
        _base_facts(buyer_role="DESIGNER_CONTRACTOR", customer_type="B2C"),
        {"furniture-designers": True, "furniture-b2b": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "raw_not_ready_rattan",
        _base_facts(vertical="ARTIFICIAL_RATTAN", rattan_layers={"RAW_MATERIAL"}),
        {"rattan-raw-buyers": True, "rattan-ready-furniture-buyers": False, "rattan-commercial": True},
    ),
    AudienceMembershipUnseenCase(
        "ready_not_raw_rattan",
        _base_facts(vertical="ARTIFICIAL_RATTAN", rattan_layers={"READY_FURNITURE"}),
        {"rattan-ready-furniture-buyers": True, "rattan-raw-buyers": False, "rattan-commercial": True},
    ),
    AudienceMembershipUnseenCase(
        "import_not_raw_seller",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_roles={"IMPORTER"},
            rattan_layers={"RAW_MATERIAL"},
        ),
        {"rattan-import-distribution": True, "rattan-raw-sellers": False, "rattan-manufacturers": False},
    ),
    AudienceMembershipUnseenCase(
        "manufacturer_not_import",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_roles={"MANUFACTURER"},
            rattan_layers={"RAW_MATERIAL"},
        ),
        {"rattan-manufacturers": True, "rattan-import-distribution": False, "rattan-raw-sellers": False},
    ),
    # --- unseen:v2 expansion: границы, негативы, слабые сегменты ---
    AudienceMembershipUnseenCase(
        "no_commercial_signal",
        _base_facts(commercial_signals=0, evidence_ids=[]),
        {
            "furniture-commercial-intent": False,
            "furniture-high-intent": False,
            "furniture-b2b": False,
            "price-sensitive-research": False,
        },
    ),
    AudienceMembershipUnseenCase(
        "high_intent_score_edge_69",
        _base_facts(current_intent_score=69, recency_days=5, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-high-intent": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "high_intent_score_edge_70",
        _base_facts(current_intent_score=70, recency_days=5, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-high-intent": True, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "high_intent_day_boundary_29",
        _base_facts(current_intent_score=80, recency_days=29, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-high-intent": True, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "high_intent_day_boundary_30",
        _base_facts(current_intent_score=80, recency_days=30, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-high-intent": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "armchair_seating_family",
        _base_facts(products={"ARMCHAIR"}),
        {"furniture-seating": True, "furniture-tables": False, "furniture-outdoor": False},
        profiles=(AudienceProfileSpec("PRODUCT", "ARMCHAIR", 2, 67, (31,)),),
    ),
    AudienceMembershipUnseenCase(
        "sofa_seating_family",
        _base_facts(products={"SOFA"}),
        {"furniture-seating": True, "furniture-dining": False, "furniture-sets": False},
        profiles=(AudienceProfileSpec("PRODUCT", "SOFA", 2, 71, (32,)),),
    ),
    AudienceMembershipUnseenCase(
        "rattan_garden_set_family",
        _base_facts(products={"RATTAN_GARDEN_SET"}),
        {"furniture-sets": True, "furniture-dining": False, "furniture-tables": False},
        profiles=(AudienceProfileSpec("PRODUCT", "RATTAN_GARDEN_SET", 2, 69, (33,)),),
    ),
    AudienceMembershipUnseenCase(
        "outdoor_not_seating",
        _base_facts(products={"OUTDOOR_FURNITURE"}),
        {
            "furniture-outdoor": True,
            "furniture-seating": False,
            "furniture-tables": False,
            "furniture-commercial-intent": True,
        },
        profiles=(AudienceProfileSpec("PRODUCT", "OUTDOOR_FURNITURE", 2, 70, (34,)),),
    ),
    AudienceMembershipUnseenCase(
        "bulk_quantity_intent_strong",
        _base_facts(intents={"QUANTITY"}, quantity=50, commercial_signals=2, evidence_ids=[1, 2]),
        {
            "bulk-quantity-intent": True,
            "furniture-b2b": False,
            "furniture-commercial-intent": True,
            "catalog-research": False,
        },
        profiles=(AudienceProfileSpec("INTENT", "QUANTITY", 3, 72, (35, 36)),),
    ),
    AudienceMembershipUnseenCase(
        "quantity_without_intent_profile",
        _base_facts(quantity=40, intents=()),
        {"bulk-quantity-intent": False, "furniture-commercial-intent": True},
    ),
    AudienceMembershipUnseenCase(
        "delivery_not_catalog",
        _base_facts(intents={"DELIVERY"}),
        {
            "logistics-ready": True,
            "catalog-research": False,
            "availability-ready": False,
            "price-sensitive-research": False,
        },
        profiles=(AudienceProfileSpec("INTENT", "DELIVERY", 2, 64, (37,)),),
    ),
    AudienceMembershipUnseenCase(
        "catalog_not_logistics",
        _base_facts(intents={"CATALOG"}),
        {
            "catalog-research": True,
            "logistics-ready": False,
            "bulk-quantity-intent": False,
            "furniture-commercial-intent": True,
        },
        profiles=(AudienceProfileSpec("INTENT", "CATALOG", 2, 59, (38,)),),
    ),
    AudienceMembershipUnseenCase(
        "comparison_window_both_fresh",
        _base_facts(sources=2, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-comparison": True, "furniture-commercial-intent": True},
        source_competitors=(101, 202),
        source_ages_days=(10, 20),
    ),
    AudienceMembershipUnseenCase(
        "comparison_window_both_stale",
        _base_facts(sources=2, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-comparison": False, "furniture-commercial-intent": True},
        source_competitors=(101, 202),
        source_ages_days=(50, 55),
    ),
    AudienceMembershipUnseenCase(
        "comparison_duplicate_competitor",
        _base_facts(sources=2, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-comparison": False, "furniture-commercial-intent": True},
        source_competitors=(101, 101),
        source_ages_days=(3, 7),
    ),
    AudienceMembershipUnseenCase(
        "b2b_horeca_wholesale_path",
        _base_facts(
            customer_type="B2B",
            buyer_role="B2B_HORECA",
            quantity=60,
            value=90,
            current_intent_score=76,
            commercial_signals=3,
            evidence_ids=[1, 2, 3],
        ),
        {
            "furniture-b2b": True,
            "furniture-high-intent": True,
            "furniture-designers": False,
            "furniture-reactivated": False,
        },
    ),
    AudienceMembershipUnseenCase(
        "designer_high_intent",
        _base_facts(
            buyer_role="DESIGNER_CONTRACTOR",
            current_intent_score=85,
            recency_days=3,
            commercial_signals=2,
            evidence_ids=[1, 2],
        ),
        {
            "furniture-designers": True,
            "furniture-high-intent": True,
            "furniture-b2b": False,
            "furniture-commercial-intent": True,
        },
    ),
    AudienceMembershipUnseenCase(
        "reactivated_not_comparison",
        _base_facts(reactivated=True, sources=1, commercial_signals=2, evidence_ids=[1, 2]),
        {
            "furniture-reactivated": True,
            "furniture-comparison": False,
            "furniture-commercial-intent": True,
        },
        source_competitors=(10,),
    ),
    AudienceMembershipUnseenCase(
        "tables_not_dining",
        _base_facts(products={"TABLE"}),
        {
            "furniture-tables": True,
            "furniture-dining": False,
            "furniture-sets": False,
            "furniture-outdoor": False,
        },
        profiles=(AudienceProfileSpec("PRODUCT", "TABLE", 2, 73, (39,)),),
    ),
    AudienceMembershipUnseenCase(
        "dining_is_also_sets",
        _base_facts(products={"DINING_SET"}),
        {
            "furniture-dining": True,
            "furniture-sets": True,
            "furniture-seating": False,
            "furniture-outdoor": False,
        },
        profiles=(AudienceProfileSpec("PRODUCT", "DINING_SET", 3, 75, (40,)),),
    ),
    AudienceMembershipUnseenCase(
        "rattan_wholesale_b2b_not_raw_buyer",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            customer_type="B2B",
            buyer_role="B2B_HORECA",
            rattan_layers=set(),
        ),
        {
            "rattan-wholesale": True,
            "rattan-commercial": True,
            "rattan-raw-buyers": False,
            "rattan-ready-furniture-buyers": False,
        },
    ),
    AudienceMembershipUnseenCase(
        "rattan_b2c_not_wholesale",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            customer_type="B2C",
            buyer_role="B2C_CONSUMER",
            rattan_layers={"READY_FURNITURE"},
        ),
        {
            "rattan-wholesale": False,
            "rattan-ready-furniture-buyers": True,
            "rattan-commercial": True,
            "furniture-b2b": False,
        },
    ),
    AudienceMembershipUnseenCase(
        "rattan_wholesaler_as_raw_seller",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_layers={"RAW_MATERIAL"},
            rattan_roles={"WHOLESALER"},
        ),
        {
            "rattan-raw-sellers": True,
            "rattan-manufacturers": False,
            "rattan-import-distribution": False,
            "rattan-raw-buyers": True,
        },
    ),
    AudienceMembershipUnseenCase(
        "rattan_distributor_import",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_layers={"RAW_MATERIAL"},
            rattan_roles={"DISTRIBUTOR"},
        ),
        {
            "rattan-import-distribution": True,
            "rattan-raw-sellers": False,
            "rattan-manufacturers": False,
        },
    ),
    AudienceMembershipUnseenCase(
        "furniture_vertical_not_rattan_commercial",
        _base_facts(vertical="FURNITURE", commercial_signals=2, evidence_ids=[1, 2]),
        {
            "rattan-commercial": False,
            "furniture-commercial-intent": True,
            "rattan-wholesale": False,
        },
    ),
    AudienceMembershipUnseenCase(
        "price_and_buy_dual_profile",
        _base_facts(intents={"PRICE", "BUY"}, current_intent_score=72, commercial_signals=2, evidence_ids=[1, 2]),
        {
            "price-sensitive-research": True,
            "furniture-high-intent": True,
            "availability-ready": False,
            "furniture-commercial-intent": True,
        },
        profiles=(
            AudienceProfileSpec("INTENT", "PRICE", 2, 60, (41,)),
            AudienceProfileSpec("INTENT", "BUY", 2, 72, (42,)),
        ),
    ),
    AudienceMembershipUnseenCase(
        "availability_and_delivery_dual",
        _base_facts(intents={"AVAILABILITY", "DELIVERY"}),
        {
            "availability-ready": True,
            "logistics-ready": True,
            "price-sensitive-research": False,
            "catalog-research": False,
        },
        profiles=(
            AudienceProfileSpec("INTENT", "AVAILABILITY", 2, 61, (43,)),
            AudienceProfileSpec("INTENT", "DELIVERY", 2, 58, (44,)),
        ),
    ),
    AudienceMembershipUnseenCase(
        "chairs_and_table_cross_family",
        _base_facts(products={"CHAIRS", "TABLE"}),
        {
            "furniture-seating": True,
            "furniture-tables": True,
            "furniture-dining": False,
            "furniture-outdoor": False,
        },
        profiles=(
            AudienceProfileSpec("PRODUCT", "CHAIRS", 2, 70, (45,)),
            AudienceProfileSpec("PRODUCT", "TABLE", 2, 68, (46,)),
        ),
    ),
    AudienceMembershipUnseenCase(
        "set_not_outdoor",
        _base_facts(products={"SET"}),
        {
            "furniture-sets": True,
            "furniture-outdoor": False,
            "furniture-seating": False,
            "furniture-commercial-intent": True,
        },
        profiles=(AudienceProfileSpec("PRODUCT", "SET", 2, 66, (47,)),),
    ),
    AudienceMembershipUnseenCase(
        "ready_seller_not_manufacturer",
        _base_facts(
            vertical="ARTIFICIAL_RATTAN",
            rattan_layers={"READY_FURNITURE"},
            rattan_roles={"FURNITURE_RESELLER"},
        ),
        {
            "rattan-ready-furniture-sellers": True,
            "rattan-manufacturers": False,
            "rattan-raw-sellers": False,
            "rattan-ready-furniture-buyers": True,
        },
    ),
    AudienceMembershipUnseenCase(
        "stale_comparison_one_fresh_source",
        _base_facts(sources=2, commercial_signals=2, evidence_ids=[1, 2]),
        {"furniture-comparison": False, "furniture-commercial-intent": True},
        source_competitors=(11, 22),
        source_ages_days=(2, 90),
    ),
)
