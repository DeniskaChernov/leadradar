from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.leads import BuyerRole


@dataclass(frozen=True, slots=True)
class B2BDecision:
    role: BuyerRole
    probability: float
    quantity: int | None
    tier: str
    evidence: tuple[str, ...]


class B2BPolicy:
    """Versioned, shared B2B decision policy based only on observable evidence."""

    VERSION = "1.0"
    CONTEXTUAL_QUANTITY = 10
    PROBABLE_QUANTITY = 30
    STRONG_QUANTITY = 50

    BUSINESS_MARKERS = (
        "для кафе",
        "для ресторана",
        "для гостиницы",
        "для отеля",
        "для офиса",
        "для объекта",
        "оптом",
        "wholesale",
        "ulgurji",
        "kafe uchun",
        "restoran uchun",
        "restoranga",
        "mehmonxona uchun",
        "ofis uchun",
        "choyxona",
        "перепрод",
        "дилер",
        "производств",
    )

    _QUANTITY_RE = re.compile(
        r"\b(\d{1,4})\s*(?:шт\w*|штук\w*|dona\w*|дона\w*|та|персон\w*|"
        r"киши\w*|kishi\w*|ta|комплект\w*|стул\w*|стол\w*|кресл\w*|диван\w*|"
        r"chair\w*|table\w*)\b"
    )

    @classmethod
    def extract_quantity(cls, text: str) -> int | None:
        values = [int(match) for match in cls._QUANTITY_RE.findall(text.lower())]
        return max(values, default=None)

    @classmethod
    def assess(
        cls,
        text: str,
        *,
        product: str | None = None,
        quantity_override: int | None = None,
    ) -> B2BDecision:
        normalized = " ".join(text.lower().replace("ё", "е").split())
        quantity = max(
            (value for value in (cls.extract_quantity(normalized), quantity_override) if value),
            default=None,
        )
        markers = tuple(marker for marker in cls.BUSINESS_MARKERS if marker in normalized)
        has_context = bool(markers) or product == "HORECA"
        evidence: list[str] = list(markers[:3])
        if quantity is not None:
            evidence.append(f"quantity:{quantity}")

        if quantity is not None and quantity >= cls.STRONG_QUANTITY:
            return B2BDecision(
                BuyerRole.B2B_HORECA, 0.98, quantity, "STRONG", tuple(evidence)
            )
        if quantity is not None and quantity >= cls.PROBABLE_QUANTITY:
            return B2BDecision(
                BuyerRole.B2B_HORECA, 0.85, quantity, "PROBABLE", tuple(evidence)
            )
        if has_context and (
            quantity is None or quantity >= cls.CONTEXTUAL_QUANTITY
        ):
            return B2BDecision(
                BuyerRole.B2B_HORECA, 0.90, quantity, "CONTEXTUAL", tuple(evidence)
            )
        if has_context:
            return B2BDecision(
                BuyerRole.B2B_HORECA, 0.75, quantity, "CONTEXTUAL", tuple(evidence)
            )
        return B2BDecision(
            BuyerRole.B2C_CONSUMER,
            0.10 if quantity is None else min(0.60, quantity / 50),
            quantity,
            "CONSUMER_OR_UNKNOWN",
            tuple(evidence),
        )
