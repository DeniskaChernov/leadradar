from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from app.db.models import Vertical


class RattanLayer(StrEnum):
    NONE = "NONE"
    RAW_MATERIAL = "RAW_MATERIAL"
    READY_FURNITURE = "READY_FURNITURE"


class RattanRole(StrEnum):
    RAW_RATTAN_RESELLER = "RAW_RATTAN_RESELLER"
    WHOLESALER = "WHOLESALER"
    IMPORTER = "IMPORTER"
    DISTRIBUTOR = "DISTRIBUTOR"
    MANUFACTURER = "MANUFACTURER"
    FURNITURE_RESELLER = "FURNITURE_RESELLER"
    WEAVER = "WEAVER"
    CRAFT_MASTER = "CRAFT_MASTER"
    BUYER = "BUYER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RattanTaxonomyResult:
    is_rattan: bool
    vertical: Vertical
    layer: RattanLayer
    role: RattanRole
    confidence: int
    products: tuple[str, ...]
    material_profiles: tuple[str, ...]
    evidence: tuple[str, ...]
    negative_evidence: tuple[str, ...]
    explanation: str


class RattanTaxonomyService:
    """Strict rattan taxonomy: generic furniture terms can never activate the vertical."""

    VERSION = "2.0"
    RATTAN_CONTEXT = (
        "искусственн rotang",
        "искусственный ротанг",
        "искусственного ротанга",
        "полиротанг",
        "техноротанг",
        "экоротанг",
        "ротанг",
        "rotang",
        "rattan",
        "polirotang",
    )
    ARTIFICIAL_CONTEXT = (
        "искусственн",
        "полиротанг",
        "техноротанг",
        "экоротанг",
        "polirotang",
        "synthetic rattan",
        "artificial rattan",
    )
    NATURAL_CONTEXT = (
        "натуральный ротанг",
        "натурального ротанга",
        "natural rattan",
        "natural rotang",
    )
    RAW_MARKERS: ClassVar[dict[str, tuple[str, ...]]] = {
        "RAW_RATTAN": ("сырье", "сырьё", "для плетения", "пруток", "лента ротанг"),
        "COIL": ("бухта", "бухтах", "рулон", "coil"),
        "KG_PRICE": ("за кг", "цена кг", "narxi kg", "kg narxi", "/кг"),
        "WIDTH": ("ширина", "width"),
        "COLOR": ("цвета", "цветовая карта", "ranglar", "color"),
    }
    PROFILE_MARKERS: ClassVar[dict[str, tuple[str, ...]]] = {
        "FLAT_RATTAN": ("плоский", "полоса", "flat"),
        "ROUND_RATTAN": ("круглый", "round"),
        "HALF_ROUND": ("полукруг", "полумесяц", "half-round", "half round"),
        "TUBE": ("трубка", "tube"),
        "PROFILE": ("профиль", "profile", "6 мм", "8 мм", "10 мм"),
    }
    FURNITURE_MARKERS: ClassVar[dict[str, tuple[str, ...]]] = {
        "RATTAN_CHAIR": ("стул", "chair"),
        "RATTAN_ARMCHAIR": ("кресло", "armchair"),
        "RATTAN_SOFA": ("диван", "sofa"),
        "RATTAN_TABLE": ("стол", "table"),
        "RATTAN_SET": ("комплект", "гарнитур", "set"),
        "RATTAN_OUTDOOR": ("садов", "террас", "outdoor"),
    }
    WHOLESALE = ("оптом", "опт", "ulgurji", "moq", "минимальный заказ", "от 50 кг")
    IMPORT = ("импорт", "import", "из китая", "bojxona")
    DISTRIBUTION = ("дистрибьютор", "официальный дилер", "distributor")
    MANUFACTURING = (
        "производство",
        "собственное производство",
        "изготавливаем",
        "цех",
        "manufactur",
    )
    WEAVING = ("плетен", "плетём", "плетем", "to'qish", "weaving")
    CRAFT = ("мастер", "ремесленник", "craft")
    BUYING = ("куплю", "нужен", "нужно", "ищу", "olaman", "kerak")
    SELLING = ("прода", "в наличии", "склад", "цена", "narxi", "sotuv")

    @classmethod
    def classify(cls, text: str) -> RattanTaxonomyResult:
        lowered = " ".join((text or "").lower().split())
        context = tuple(marker for marker in cls.RATTAN_CONTEXT if marker in lowered)
        natural_only = any(marker in lowered for marker in cls.NATURAL_CONTEXT) and not any(
            marker in lowered for marker in cls.ARTIFICIAL_CONTEXT
        )
        if not context or natural_only:
            generic = tuple(
                marker
                for markers in cls.FURNITURE_MARKERS.values()
                for marker in markers
                if marker in lowered
            )
            return RattanTaxonomyResult(
                is_rattan=False,
                vertical=Vertical.FURNITURE,
                layer=RattanLayer.NONE,
                role=RattanRole.UNKNOWN,
                confidence=100 if generic else 80,
                products=(),
                material_profiles=(),
                evidence=(),
                negative_evidence=(
                    "natural_rattan_out_of_scope"
                    if natural_only
                    else "no_explicit_rattan_context",
                ),
                explanation=(
                    "Натуральный ротанг не относится к вертикали искусственного ротанга."
                    if natural_only
                    else "Нет явного контекста искусственного ротанга."
                ),
            )

        products = tuple(
            topic
            for topic, markers in cls.FURNITURE_MARKERS.items()
            if any(marker in lowered for marker in markers)
        )
        raw_topics = tuple(
            topic
            for topic, markers in cls.RAW_MARKERS.items()
            if any(marker in lowered for marker in markers)
        )
        profiles = tuple(
            topic
            for topic, markers in cls.PROFILE_MARKERS.items()
            if any(marker in lowered for marker in markers)
        )
        raw = bool(raw_topics or profiles)
        ready = bool(products)
        raw_market_role_context = any(
            marker in lowered
            for marker in (
                *cls.WHOLESALE,
                *cls.IMPORT,
                *cls.DISTRIBUTION,
                *cls.MANUFACTURING,
                *cls.WEAVING,
                *cls.CRAFT,
                *cls.BUYING,
            )
        )
        negative: list[str] = []
        if raw:
            layer = RattanLayer.RAW_MATERIAL
            evidence = ["explicit_rattan_context", "raw_material_context"]
            if profiles:
                evidence.append("material_profile_specification")
        elif ready:
            layer = RattanLayer.READY_FURNITURE
            evidence = ["explicit_rattan_context", "ready_furniture_context"]
            negative.append("no_raw_material_evidence")
        elif raw_market_role_context:
            layer = RattanLayer.RAW_MATERIAL
            raw_topics = ("RAW_RATTAN",)
            evidence = ["explicit_rattan_context", "raw_market_role_context"]
        else:
            layer = RattanLayer.NONE
            evidence = ["explicit_rattan_context"]
            negative.append("insufficient_layer_evidence")

        role = cls._role(lowered, layer)
        if any(marker in lowered for marker in cls.WHOLESALE):
            evidence.append("wholesale_context")
        if role != RattanRole.UNKNOWN:
            evidence.append(f"role:{role.value}")
        confidence = min(98, 68 + 8 * len(set(evidence)) + 4 * len(profiles))
        return RattanTaxonomyResult(
            is_rattan=True,
            vertical=Vertical.ARTIFICIAL_RATTAN,
            layer=layer,
            role=role,
            confidence=confidence,
            products=products or raw_topics,
            material_profiles=profiles,
            evidence=tuple(dict.fromkeys(evidence)),
            negative_evidence=tuple(negative),
            explanation=(
                "Сырьевой рынок искусственного ротанга."
                if layer == RattanLayer.RAW_MATERIAL
                else "Готовая мебель с явным контекстом ротанга."
                if layer == RattanLayer.READY_FURNITURE
                else "Контекст ротанга подтверждён, но тип рынка пока не доказан."
            ),
        )

    @classmethod
    def _role(cls, text: str, layer: RattanLayer) -> RattanRole:
        if any(marker in text for marker in cls.BUYING):
            return RattanRole.BUYER
        if any(marker in text for marker in cls.IMPORT):
            return RattanRole.IMPORTER
        if any(marker in text for marker in cls.DISTRIBUTION):
            return RattanRole.DISTRIBUTOR
        if any(marker in text for marker in cls.MANUFACTURING):
            return RattanRole.MANUFACTURER
        if any(marker in text for marker in cls.WHOLESALE):
            return RattanRole.WHOLESALER
        if any(marker in text for marker in cls.WEAVING):
            return RattanRole.WEAVER
        if any(marker in text for marker in cls.CRAFT):
            return RattanRole.CRAFT_MASTER
        if layer == RattanLayer.RAW_MATERIAL and any(marker in text for marker in cls.SELLING):
            return RattanRole.RAW_RATTAN_RESELLER
        if layer == RattanLayer.READY_FURNITURE and any(
            marker in text for marker in cls.SELLING
        ):
            return RattanRole.FURNITURE_RESELLER
        return RattanRole.UNKNOWN
