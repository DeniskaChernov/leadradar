"""The owner's assortment, independent of what a competitor happens to sell."""

from dataclasses import dataclass

from sqlalchemy import or_

from app.schemas.leads import CommercialSignalQuality, FunnelStage, LeadAnalysis, Urgency
from app.services.product_context_service import resolve_product_context

ASSORTMENT_VERSION = "btt-furniture:2026-10-13"
ASSORTMENT_DESCRIPTION = (
    "Плетёная мебель, пластиковые стулья, обеденные комплекты, мебель из искусственного "
    "ротанга, плетёные кресла, обеденные стулья и мебель для HoReCa."
)
UNSUPPORTED_CATEGORIES = frozenset({
    "SOFA", "RATTAN_SOFA", "BED", "DRESSER", "COMPUTER_DESK", "OFFICE_CHAIR",
    "WARDROBE", "KITCHEN_CABINET", "SHELVING", "HALLWAY", "LAMP", "PERGOLA",
})


def assortment_eligible(details: dict | None) -> bool:
    return ((details or {}).get("assortment") or {}).get("status") not in {"EXCLUDED", "REVIEW"}


def assortment_eligible_clause(model):
    status = model.analysis_details["assortment"]["status"].as_string()
    return or_(status.is_(None), status.notin_(["EXCLUDED", "REVIEW"]))


@dataclass(frozen=True, slots=True)
class AssortmentDecision:
    status: str
    categories: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict:
        return {"version": ASSORTMENT_VERSION, "status": self.status,
                "categories": list(self.categories), "reason": self.reason}


def assess_assortment(comment: str, caption: str, parent: str = "", *,
                      vertical: str = "FURNITURE") -> AssortmentDecision:
    if vertical != "FURNITURE":
        return AssortmentDecision("OTHER_VERTICAL", (), "Отдельное направление сырья.")
    product = resolve_product_context(comment, caption, parent)
    categories = product.categories
    rejected = set(categories) & UNSUPPORTED_CATEGORIES
    if rejected and rejected == set(categories):
        return AssortmentDecision("EXCLUDED", categories, "Запрошенный товар отсутствует в нашем ассортименте.")
    if rejected:
        return AssortmentDecision("REVIEW", categories,
                                  "В запросе есть товары вне ассортимента. Уточнить подходящие позиции.")
    if categories and not (set(categories) & {"ARMCHAIR", "SWING"}):
        return AssortmentDecision("MATCH", categories, "Товар относится к нашему ассортименту.")
    text = f"{comment} {parent} {caption}".lower()
    if not categories and any(word in text for word in ("horeca", "ho-re-ca", "хорека", "мебель для кафе", "мебель для ресторана")):
        return AssortmentDecision("MATCH", (), "Запрос на мебель для HoReCa; модель нужно уточнить.")
    return AssortmentDecision("REVIEW", categories,
                              "Нужно подтвердить, что интерес относится к нашему ассортименту.")


def apply_assortment(analysis: LeadAnalysis, decision: AssortmentDecision) -> LeadAnalysis:
    if decision.status not in {"EXCLUDED", "REVIEW"} or (decision.status == "REVIEW" and not analysis.is_lead):
        return analysis
    excluded = decision.status == "EXCLUDED"
    score = 0 if excluded else min(analysis.lead_score, 60)
    clarification = "Сначала уточнить товар и соответствие ассортименту. После подтверждения: "
    action = ("Сохранить как неподходящий запрос; товар не предлагать." if excluded else
              analysis.recommended_action if analysis.recommended_action.startswith(clarification) else
              clarification + analysis.recommended_action)
    return analysis.model_copy(update={
        "is_lead": False if excluded else analysis.is_lead,
        "lead_score": score, "priority_score": score, "fit_score": 0,
        "confidence": analysis.confidence if excluded else min(analysis.confidence, 60),
        "is_commercial": False,
        "commercial_quality": CommercialSignalQuality.NON_COMMERCIAL,
        "commercial_stage": FunnelStage.NON_COMMERCIAL,
        "funnel_stage": FunnelStage.NON_COMMERCIAL if excluded else FunnelStage.AWARENESS,
        "urgency": Urgency.LOW, "reason": decision.reason, "short_reason": decision.reason,
        "recommended_action": action, "next_best_action": action,
        "risk_flags": list(dict.fromkeys(["Не наш ассортимент" if excluded else "Ассортимент требует уточнения", *analysis.risk_flags]))[:6],
        "factors": analysis.factors.model_copy(update={"fit_score": 0, "priority_score": score}),
    })
