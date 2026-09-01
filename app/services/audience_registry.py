"""Finite, governed registry of durable Lead Radar audiences.

Audience definitions describe stable commercial cohorts. Runtime dimensions such
as city, exact quantity, dates, managers and individual competitors are facets;
they must never create another persisted audience definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

AUDIENCE_FACETS = frozenset(
    {
        "vertical",
        "product_family",
        "intent",
        "buyer_role",
        "commercial_stage",
        "quantity_band",
        "city",
        "source_competitor",
        "recency_bucket",
        "confidence_band",
        "value_band",
        "purchase_horizon",
        "rattan_layer",
        "rattan_role",
        "manager_status",
        "won_status",
    }
)

PROHIBITED_DEFINITION_CRITERIA = frozenset(
    {
        "city",
        "district",
        "age",
        "gender",
        "exact_score",
        "exact_quantity",
        "exact_date",
        "manager",
        "competitor",
        "reel",
        "post",
        "sku",
        "color",
        "dimensions",
        "language",
    }
)


@dataclass(frozen=True, slots=True)
class AudienceDefinition:
    slug: str
    name: str
    description: str
    audience_family: str
    criteria: dict[str, Any]
    vertical: str = "FURNITURE"
    audience_level: str = "CORE"
    status: str = "ACTIVE"
    membership_strategy: str = "RULE"
    minimum_evidence_count: int = 1
    minimum_confidence: int = 50
    minimum_current_score: int = 20
    recency_policy: dict[str, Any] | None = None
    decay_policy: dict[str, Any] | None = None
    meta_use_case: str = "ANALYSIS_ONLY"
    created_by: str = "SYSTEM_REGISTRY"
    engine_version: str = "4.0"


def _definition(
    slug: str,
    name: str,
    description: str,
    family: str,
    criteria: dict[str, Any],
    **kwargs: Any,
) -> AudienceDefinition:
    return AudienceDefinition(slug, name, description, family, criteria, **kwargs)


AUDIENCE_DEFINITIONS = (
    _definition(
        "furniture-commercial-intent",
        "Мебель · Коммерческий интерес",
        "Текущий подтверждённый спрос на мебель.",
        "INTENT",
        {"min_commercial_signals": 1},
    ),
    _definition(
        "furniture-high-intent",
        "Мебель · Высокий покупательский интерес",
        "Сильный текущий покупательский интерес, а не исторический максимум.",
        "INTENT",
        {"min_current_intent": 70, "days": 30},
        minimum_current_score=70,
        meta_use_case="RETARGETING",
    ),
    _definition(
        "furniture-b2b",
        "Мебель · B2B / HoReCa",
        "Подтверждённый коммерческий или оптовый спрос.",
        "BUYER_ROLE",
        {"customer_type": "B2B"},
    ),
    _definition(
        "furniture-designers",
        "Мебель · Дизайнеры и комплектаторы",
        "Подтверждённая роль дизайнера или комплектатора.",
        "BUYER_ROLE",
        {"buyer_role": "DESIGNER_CONTRACTOR"},
    ),
    _definition(
        "furniture-comparison",
        "Мебель · Сравнивают предложения",
        "Текущий коммерческий спрос у двух и более независимых продавцов.",
        "MARKET_BEHAVIOR",
        {"sources": 2, "days": 45, "source_window_days": 45},
        minimum_evidence_count=2,
    ),
    _definition(
        "furniture-reactivated",
        "Мебель · Возврат интереса",
        "Новый коммерческий сигнал после длительной паузы.",
        "LIFECYCLE",
        {"reactivated": True},
    ),
    _definition(
        "furniture-seating",
        "Мебель · Стулья и кресла",
        "Устойчивое семейство посадочной мебели.",
        "PRODUCT",
        {"products": ["CHAIRS", "ARMCHAIR", "SOFA"]},
    ),
    _definition(
        "furniture-tables",
        "Мебель · Столы",
        "Устойчивое семейство столов.",
        "PRODUCT",
        {"products": ["TABLE"]},
    ),
    _definition(
        "furniture-dining",
        "Мебель · Обеденная зона",
        "Обеденные группы и мебель для столовой зоны.",
        "PRODUCT",
        {"products": ["DINING_SET"]},
    ),
    _definition(
        "furniture-outdoor",
        "Мебель · Outdoor / террасы",
        "Мебель для улицы, сада и террас.",
        "PRODUCT",
        {"products": ["OUTDOOR_FURNITURE"]},
    ),
    _definition(
        "furniture-sets",
        "Мебель · Комплекты",
        "Комплекты мебели как устойчивая товарная семья.",
        "PRODUCT",
        {"products": ["SET", "DINING_SET", "RATTAN_GARDEN_SET"]},
    ),
    _definition(
        "price-sensitive-research",
        "Исследуют цену",
        "Подтверждённо изучают цену или стоимость.",
        "INTENT",
        {"intent": "PRICE"},
        audience_level="SPECIALIZED",
    ),
    _definition(
        "availability-ready",
        "Проверяют наличие",
        "Уточняют текущее наличие товара.",
        "INTENT",
        {"intent": "AVAILABILITY"},
        audience_level="SPECIALIZED",
    ),
    _definition(
        "logistics-ready",
        "Уточняют доставку",
        "Обсуждают доставку или логистику.",
        "INTENT",
        {"intent": "DELIVERY"},
        audience_level="SPECIALIZED",
    ),
    _definition(
        "bulk-quantity-intent",
        "Запрашивают количество / объём",
        "Коммерческий запрос объёма без дробления по точным порогам.",
        "INTENT",
        {"intent": "QUANTITY"},
        audience_level="SPECIALIZED",
    ),
    _definition(
        "catalog-research",
        "Изучают ассортимент",
        "Запрашивают каталог или варианты ассортимента.",
        "INTENT",
        {"intent": "CATALOG"},
        audience_level="SPECIALIZED",
    ),
    _definition(
        "rattan-commercial",
        "Искусственный ротанг · Коммерческий рынок",
        "Подтверждённый коммерческий сигнал рынка искусственного ротанга.",
        "RATTAN_MARKET",
        {"min_commercial_signals": 1},
        vertical="ARTIFICIAL_RATTAN",
    ),
    _definition(
        "rattan-raw-buyers",
        "Ротанг · Покупатели сырья",
        "Покупательский спрос на сырьё и профиль для плетения.",
        "RATTAN_MARKET",
        {"rattan_layer": "RAW_MATERIAL"},
        vertical="ARTIFICIAL_RATTAN",
        audience_level="SPECIALIZED",
    ),
    _definition(
        "rattan-raw-sellers",
        "Ротанг · Поставщики сырья",
        "Поставщики сырья, требующие подтверждённой рыночной роли.",
        "RATTAN_MARKET",
        {"rattan_role": "RAW_SELLER"},
        vertical="ARTIFICIAL_RATTAN",
        audience_level="EXPERIMENTAL",
        status="DRAFT",
    ),
    _definition(
        "rattan-wholesale",
        "Ротанг · Опт",
        "Оптовый спрос в вертикали искусственного ротанга.",
        "RATTAN_MARKET",
        {"customer_type": "B2B"},
        vertical="ARTIFICIAL_RATTAN",
    ),
    _definition(
        "rattan-manufacturers",
        "Ротанг · Производители",
        "Производители с подтверждённой рыночной ролью.",
        "RATTAN_MARKET",
        {"rattan_role": "MANUFACTURER"},
        vertical="ARTIFICIAL_RATTAN",
        audience_level="EXPERIMENTAL",
        status="DRAFT",
    ),
    _definition(
        "rattan-ready-furniture-buyers",
        "Ротанг · Покупатели готовой мебели",
        "Покупательский спрос на готовую мебель из ротанга.",
        "RATTAN_MARKET",
        {"rattan_layer": "READY_FURNITURE"},
        vertical="ARTIFICIAL_RATTAN",
        audience_level="SPECIALIZED",
    ),
    _definition(
        "rattan-ready-furniture-sellers",
        "Ротанг · Продавцы готовой мебели",
        "Продавцы с подтверждённой рыночной ролью.",
        "RATTAN_MARKET",
        {"rattan_role": "READY_FURNITURE_SELLER"},
        vertical="ARTIFICIAL_RATTAN",
        audience_level="EXPERIMENTAL",
        status="DRAFT",
    ),
    _definition(
        "rattan-import-distribution",
        "Ротанг · Импорт / дистрибуция",
        "Импортёры и дистрибьюторы с подтверждённой ролью.",
        "RATTAN_MARKET",
        {"rattan_role": "IMPORT_DISTRIBUTION"},
        vertical="ARTIFICIAL_RATTAN",
        audience_level="EXPERIMENTAL",
        status="DRAFT",
    ),
    _definition(
        "won-customer-seed",
        "Покупатели · WON Seed",
        "Первичные данные выигранных сделок.",
        "OUTCOME_DNA",
        {"won_status": "WON"},
        status="DRAFT",
        membership_strategy="OUTCOME",
        meta_use_case="LOOKALIKE_SEED",
    ),
    _definition(
        "won-b2b-seed",
        "B2B WON Seed",
        "Выигранные B2B-сделки с доказательной историей.",
        "OUTCOME_DNA",
        {"won_status": "WON", "customer_type": "B2B"},
        status="DRAFT",
        membership_strategy="OUTCOME",
        meta_use_case="LOOKALIKE_SEED",
    ),
    _definition(
        "high-value-won-seed",
        "High Value WON Seed",
        "Высокоценные выигранные сделки.",
        "OUTCOME_DNA",
        {"won_status": "WON", "value_band": "HIGH"},
        status="DRAFT",
        membership_strategy="OUTCOME",
        meta_use_case="LOOKALIKE_SEED",
    ),
    _definition(
        "similar-to-won",
        "Похожие на WON",
        "Внутренняя аудитория сходства с доказанными покупателями.",
        "SIMILARITY",
        {"similarity_target": "WON"},
        status="DRAFT",
        membership_strategy="DNA_SIMILARITY",
        meta_use_case="ANALYSIS_ONLY",
    ),
)

AUDIENCE_BY_SLUG = {definition.slug: definition for definition in AUDIENCE_DEFINITIONS}
ACTIVE_AUDIENCE_DEFINITIONS = tuple(
    definition for definition in AUDIENCE_DEFINITIONS if definition.status == "ACTIVE"
)

LEGACY_AUDIENCE_SLUGS = frozenset(
    {
        "hot-24h",
        "hot-7d",
        "hot-30d",
        "dining-sets",
        "tables",
        "chairs",
        "outdoor",
        "rattan",
        "asked-price",
        "asked-availability",
        "asked-delivery",
        "asked-quantity",
        "multi-competitor-2",
        "multi-competitor-3",
        "b2b",
        "quantity-20",
        "quantity-50",
        "reactivated",
        "rattan-high-value",
        "rattan-raw-material",
        "rattan-ready-furniture",
        "designers",
        "horeca-b2b",
        "high-intent-b2c",
        "comparison-shoppers",
    }
)


def validate_registry() -> None:
    slugs = [definition.slug for definition in AUDIENCE_DEFINITIONS]
    if len(slugs) != len(set(slugs)):
        raise ValueError("Audience registry contains duplicate slugs")
    for definition in AUDIENCE_DEFINITIONS:
        prohibited = PROHIBITED_DEFINITION_CRITERIA.intersection(definition.criteria)
        if prohibited:
            raise ValueError(
                f"Audience {definition.slug} uses facet-only criteria: {sorted(prohibited)}"
            )
        if definition.minimum_evidence_count < 1:
            raise ValueError(f"Audience {definition.slug} has no evidence floor")


validate_registry()
