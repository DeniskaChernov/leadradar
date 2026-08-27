"""
evidence_bundle_service.py — V6 Intelligence V3 & EvidenceBundle Multi-Score Engine.

Decomposes lead intelligence into transparent, verifiable factors:
  - intent_score (0..100)
  - activity_score (0..100)
  - specificity_score (0..100)
  - value_score (0..100)
  - fit_score (0..100)
  - source_quality_score (0..100)
  - urgency_score (0..100)
  - confidence_score (0..100)
  - B2B_probability (0.0..1.0)
  - B2C_probability (0.0..1.0)
  - priority_score (0..100)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DecomposedLeadScore:
    intent_score: int
    activity_score: int
    specificity_score: int
    value_score: int
    fit_score: int
    source_quality_score: int
    urgency_score: int
    confidence_score: int
    b2b_probability: float
    b2c_probability: float
    priority_score: int
    evidence_ids: Sequence[str] = field(default_factory=list)
    explanation: str = ""


class EvidenceBundleEngine:
    """Decomposes lead intelligence into multi-factor scores and priority formula."""

    @classmethod
    def decompose_lead_score(
        cls,
        *,
        intent_score: int,
        activity_score: int,
        specificity_score: int,
        value_score: int,
        fit_score: int,
        source_quality_score: int = 80,
        urgency_score: int = 50,
        confidence_score: int = 85,
        b2b_probability: float = 0.2,
        b2c_probability: float = 0.8,
        evidence_ids: Sequence[str] = (),
    ) -> DecomposedLeadScore:
        priority_base = (
            0.30 * intent_score
            + 0.20 * activity_score
            + 0.15 * specificity_score
            + 0.15 * value_score
            + 0.10 * fit_score
            + 0.05 * urgency_score
            + 0.05 * source_quality_score
        )
        priority = round(min(100.0, max(0.0, priority_base * (confidence_score / 100.0))))

        explanation = (
            f"Приоритет {priority}/100 рассчитан из намерений ({intent_score}), активности ({activity_score}), "
            f"специфичности ({specificity_score}) и стоимости ({value_score}) при уверенности {confidence_score}%."
        )

        return DecomposedLeadScore(
            intent_score=intent_score,
            activity_score=activity_score,
            specificity_score=specificity_score,
            value_score=value_score,
            fit_score=fit_score,
            source_quality_score=source_quality_score,
            urgency_score=urgency_score,
            confidence_score=confidence_score,
            b2b_probability=round(b2b_probability, 2),
            b2c_probability=round(b2c_probability, 2),
            priority_score=priority,
            evidence_ids=list(evidence_ids),
            explanation=explanation,
        )
