"""
rattan_classifier_service.py — V6 Artificial Rattan Business Role & Reseller/Wholesaler Classifier.

Implements evidence-backed classification of artificial rattan companies:
  - RAW_RATTAN_RESELLER
  - RAW_RATTAN_WHOLESALER
  - RAW_RATTAN_IMPORTER
  - RAW_RATTAN_DISTRIBUTOR
  - RATTAN_FURNITURE_MANUFACTURER
  - RATTAN_FURNITURE_RESELLER
  - WEAVER
  - CRAFT_MASTER
  - MARKETPLACE_SELLER
  - HORECA_BUYER
  - RAW_RATTAN_BUYER
  - UNKNOWN
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RattanClassificationResult:
    primary_role: str
    confidence: int  # 0..100
    reseller_probability: float  # 0.0..1.0
    wholesaler_probability: float  # 0.0..1.0
    importer_probability: float  # 0.0..1.0
    distributor_probability: float  # 0.0..1.0
    manufacturer_probability: float  # 0.0..1.0
    buyer_probability: float  # 0.0..1.0
    evidence_ids: list[str] = field(default_factory=list)
    negative_evidence_ids: list[str] = field(default_factory=list)
    explanation: str = ""


class RattanBusinessClassifier:
    """Deterministic & evidence-backed classifier for artificial rattan market players."""

    RAW_MARKERS: Sequence[str] = (
        "искусственный ротанг",
        "ротанг для плетения",
        "полиротанг",
        "техноротанг",
        "экоротанг",
        "ротанг в бухтах",
        "ротанг кг",
        "цена за кг",
        "narxi kg",
        "rotang ulgurji",
    )

    WHOLESALE_MARKERS: Sequence[str] = (
        "оптом",
        "опт",
        "ulgurji",
        "оптовые цены",
        "минимальный заказ",
        "moq",
        "от 100 кг",
        "от 50 кг",
        "тонна",
        "бухта",
    )

    PROFILE_MARKERS: Sequence[str] = (
        "6 мм",
        "8 мм",
        "10 мм",
        "полукруг",
        "трубка",
        "полоса",
        "полумесяц",
        "flat",
        "half-round",
        "tube",
    )

    MANUFACTURING_MARKERS: Sequence[str] = (
        "производство мебели",
        "плетение мебели",
        "собственное производство",
        "цех",
        "мастерская",
        "изготовление на заказ",
        "завод ротанга",
    )

    @classmethod
    def classify_text(cls, text: str, *, context_url: str = "") -> RattanClassificationResult:
        lowered = (text or "").lower()
        evidence_ids: list[str] = []
        negative_ids: list[str] = []

        raw_count = sum(1 for m in cls.RAW_MARKERS if m in lowered)
        wholesale_count = sum(1 for m in cls.WHOLESALE_MARKERS if m in lowered)
        profile_count = sum(1 for m in cls.PROFILE_MARKERS if m in lowered)
        mfg_count = sum(1 for m in cls.MANUFACTURING_MARKERS if m in lowered)

        if raw_count > 0:
            evidence_ids.append("ev_raw_rattan_terms")
        if wholesale_count > 0:
            evidence_ids.append("ev_wholesale_terms")
        if profile_count > 0:
            evidence_ids.append("ev_profile_specifications")
        if mfg_count > 0:
            evidence_ids.append("ev_manufacturing_terms")

        # Calculate probabilities
        reseller_prob = min(1.0, (raw_count * 0.25) + (profile_count * 0.20))
        wholesaler_prob = min(1.0, (raw_count * 0.20) + (wholesale_count * 0.35))
        mfg_prob = min(1.0, (mfg_count * 0.40) + (raw_count * 0.15))
        importer_prob = 0.8 if "импорт" in lowered or "производитель ротанга" in lowered else 0.2
        distributor_prob = 0.7 if "дистрибьютор" in lowered or "официальный дилер" in lowered else 0.2
        buyer_prob = 0.8 if ("куплю" in lowered or "нужен ротанг" in lowered) else 0.1

        # Primary role determination
        primary_role = "UNKNOWN"
        confidence = 40
        explanation = "Недостаточно коммерческих сигналов по ротангу."

        if buyer_prob >= 0.7:
            primary_role = "RAW_RATTAN_BUYER"
            confidence = 85
            explanation = "Обнаружен прямой запрос на покупку сырьевого ротанга."
        elif wholesaler_prob >= 0.6 and reseller_prob >= 0.5:
            primary_role = "RAW_RATTAN_WHOLESALER"
            confidence = 90
            explanation = "Обнаружено предложение сырьевого ротанга оптом в бухтах/килограммах."
        elif reseller_prob >= 0.5:
            primary_role = "RAW_RATTAN_RESELLER"
            confidence = 80
            explanation = "Обнаружена розничная/мелкооптовая продажа искусственного ротанга."
        elif mfg_prob >= 0.5:
            primary_role = "RATTAN_FURNITURE_MANUFACTURER"
            confidence = 85
            explanation = "Обнаружено собственное производство/плетение ротанговой мебели."
        elif raw_count == 0 and ("диван" in lowered or "кресло" in lowered or "стол" in lowered):
            primary_role = "RATTAN_FURNITURE_RESELLER"
            confidence = 75
            negative_ids.append("ev_no_raw_rattan_materials")
            explanation = "Продажа готовой плетёной мебели без признаков торговли сырьём."

        return RattanClassificationResult(
            primary_role=primary_role,
            confidence=confidence,
            reseller_probability=round(reseller_prob, 2),
            wholesaler_probability=round(wholesaler_prob, 2),
            importer_probability=round(importer_prob, 2),
            distributor_probability=round(distributor_prob, 2),
            manufacturer_probability=round(mfg_prob, 2),
            buyer_probability=round(buyer_prob, 2),
            evidence_ids=evidence_ids,
            negative_evidence_ids=negative_ids,
            explanation=explanation,
        )
