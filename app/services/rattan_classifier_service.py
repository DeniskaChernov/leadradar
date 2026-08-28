from __future__ import annotations

from dataclasses import dataclass, field

from app.services.rattan_taxonomy_service import (
    RattanLayer,
    RattanRole,
    RattanTaxonomyService,
)


@dataclass(frozen=True, slots=True)
class RattanClassificationResult:
    primary_role: str
    confidence: int
    reseller_probability: float
    wholesaler_probability: float
    importer_probability: float
    distributor_probability: float
    manufacturer_probability: float
    buyer_probability: float
    evidence_ids: list[str] = field(default_factory=list)
    negative_evidence_ids: list[str] = field(default_factory=list)
    explanation: str = ""


class RattanBusinessClassifier:
    """Compatibility adapter over the strict, versioned rattan taxonomy."""

    @classmethod
    def classify_text(cls, text: str, *, context_url: str = "") -> RattanClassificationResult:
        del context_url
        result = RattanTaxonomyService.classify(text)
        role_map = {
            RattanRole.WHOLESALER: "RAW_RATTAN_WHOLESALER",
            RattanRole.IMPORTER: "RAW_RATTAN_IMPORTER",
            RattanRole.DISTRIBUTOR: "RAW_RATTAN_DISTRIBUTOR",
            RattanRole.MANUFACTURER: "RATTAN_FURNITURE_MANUFACTURER",
            RattanRole.FURNITURE_RESELLER: "RATTAN_FURNITURE_RESELLER",
            RattanRole.BUYER: (
                "RAW_RATTAN_BUYER"
                if result.layer == RattanLayer.RAW_MATERIAL
                else "RATTAN_FURNITURE_BUYER"
            ),
        }
        primary_role = role_map.get(result.role, result.role.value)
        evidence_map = {
            "explicit_rattan_context": "ev_raw_rattan_terms",
            "raw_material_context": "ev_raw_rattan_terms",
            "material_profile_specification": "ev_profile_specifications",
            "ready_furniture_context": "ev_ready_rattan_furniture",
            "wholesale_context": "ev_wholesale_terms",
            "role:MANUFACTURER": "ev_manufacturing_terms",
        }
        evidence_ids = list(
            dict.fromkeys(evidence_map.get(item, item) for item in result.evidence)
        )
        negative_ids = [
            "ev_no_raw_rattan_materials"
            if item == "no_raw_material_evidence"
            else item
            for item in result.negative_evidence
        ]
        role_confidence = result.confidence / 100 if result.is_rattan else 0.0
        return RattanClassificationResult(
            primary_role=primary_role,
            confidence=result.confidence,
            reseller_probability=(
                role_confidence
                if result.role
                in {RattanRole.RAW_RATTAN_RESELLER, RattanRole.FURNITURE_RESELLER}
                else 0.0
            ),
            wholesaler_probability=(
                role_confidence if result.role == RattanRole.WHOLESALER else 0.0
            ),
            importer_probability=(
                role_confidence if result.role == RattanRole.IMPORTER else 0.0
            ),
            distributor_probability=(
                role_confidence if result.role == RattanRole.DISTRIBUTOR else 0.0
            ),
            manufacturer_probability=(
                role_confidence if result.role == RattanRole.MANUFACTURER else 0.0
            ),
            buyer_probability=role_confidence if result.role == RattanRole.BUYER else 0.0,
            evidence_ids=evidence_ids,
            negative_evidence_ids=negative_ids,
            explanation=result.explanation,
        )
