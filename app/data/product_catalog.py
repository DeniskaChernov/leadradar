from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.db.models import Vertical


@dataclass(frozen=True, slots=True)
class ConfirmedProductSeed:
    canonical_key: str
    name: str
    price: Decimal
    dimensions_cm: dict[str, float] | None = None
    max_load_kg: Decimal | None = None
    minimum_order_quantity: int | None = None
    vertical: Vertical = Vertical.ARTIFICIAL_RATTAN


CONFIRMED_PRODUCTS: tuple[ConfirmedProductSeed, ...] = (
    ConfirmedProductSeed(
        "corda-57x63x77",
        "CORDA",
        Decimal("33.00"),
        {"length": 57, "width": 63, "height": 77},
        minimum_order_quantity=100,
    ),
    ConfirmedProductSeed(
        "vertex-57x63x75",
        "VERTEX",
        Decimal("33.00"),
        {"length": 57, "width": 63, "height": 75},
        minimum_order_quantity=100,
    ),
    ConfirmedProductSeed(
        "taper-rotang-80x80x75",
        "TAPER ROTANG",
        Decimal("40.95"),
        {"length": 80, "width": 80, "height": 75},
    ),
    ConfirmedProductSeed(
        "taper-rotang-135x80x75",
        "TAPER ROTANG",
        Decimal("47.62"),
        {"length": 135, "width": 80, "height": 75},
    ),
    ConfirmedProductSeed("todo", "TODO", Decimal("18.00"), max_load_kg=Decimal("180")),
    ConfirmedProductSeed("roero", "ROERO", Decimal("14.00"), max_load_kg=Decimal("120")),
    ConfirmedProductSeed("noero", "NOERO", Decimal("16.00"), max_load_kg=Decimal("120")),
    ConfirmedProductSeed(
        "jardin-73.5x53.5x55.5",
        "JARDIN",
        Decimal("27.00"),
        {"length": 73.5, "width": 53.5, "height": 55.5},
        max_load_kg=Decimal("150"),
    ),
    ConfirmedProductSeed(
        "lira-95x55x48",
        "LIRA",
        Decimal("29.50"),
        {"length": 95, "width": 55, "height": 48},
    ),
    ConfirmedProductSeed(
        "como-82x63x60",
        "COMO",
        Decimal("40.47"),
        {"length": 82, "width": 63, "height": 60},
    ),
)

CATALOG_SOURCE_REFERENCE = "MASTER TECHNICAL SPECIFICATION §41"
