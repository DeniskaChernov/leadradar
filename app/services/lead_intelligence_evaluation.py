from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.schemas.leads import BuyerRole, Intent
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer


@dataclass(frozen=True, slots=True)
class LeadEvaluationReport:
    scenario_count: int
    lead_precision: float
    lead_recall: float
    intent_accuracy: float
    buyer_role_accuracy: float
    hot_false_positive_rate: float
    b2b_precision: float
    mismatch_ids: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.scenario_count >= 200
            and self.lead_precision >= 0.95
            and self.lead_recall >= 0.95
            and self.intent_accuracy >= 0.90
            and self.buyer_role_accuracy >= 0.90
            and self.hot_false_positive_rate <= 0.02
            and self.b2b_precision >= 0.95
        )


class LeadIntelligenceEvaluation:
    """Deterministic semantic benchmark; no provider or database access."""

    def __init__(self, fixture_path: str | Path = "fixtures/lead_intelligence_v3_eval.json"):
        self.fixture_path = Path(fixture_path)
        self.analyzer = RuleBasedLeadAnalyzer()

    def evaluate(self, *, hot_threshold: int = 70) -> LeadEvaluationReport:
        groups = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        true_positive = false_positive = false_negative = 0
        intent_matches = role_matches = 0
        non_lead_count = hot_false_positives = 0
        predicted_b2b = correct_b2b = 0
        mismatches: list[str] = []
        scenario_count = 0

        for group in groups:
            for index, phrase in enumerate(group["phrases"]):
                scenario_count += 1
                case_id = f"{group['id']}:{index}"
                expected_lead = bool(group["lead"])
                expected_intent = Intent(group["intent"])
                expected_role = BuyerRole(group["role"])
                analysis = self.analyzer.classify(
                    LeadAnalysisContext(
                        competitor="evaluation-source",
                        post_caption=str(group["caption"]),
                        comment=str(phrase),
                        username=f"evaluation_{scenario_count}",
                        previous_signals=[],
                        previous_interests=[],
                        evidence_ids=[scenario_count],
                    )
                )
                actual_lead = bool(analysis and analysis.is_lead)
                actual_intent = analysis.intent if analysis else Intent.OTHER
                actual_role = analysis.buyer_role if analysis else BuyerRole.UNKNOWN
                actual_score = analysis.lead_score if analysis else 0

                true_positive += int(expected_lead and actual_lead)
                false_positive += int(not expected_lead and actual_lead)
                false_negative += int(expected_lead and not actual_lead)
                intent_matches += int(actual_intent == expected_intent)
                role_matches += int(actual_role == expected_role)
                if not expected_lead:
                    non_lead_count += 1
                    hot_false_positives += int(actual_score >= hot_threshold)
                if actual_role == BuyerRole.B2B_HORECA:
                    predicted_b2b += 1
                    correct_b2b += int(expected_role == BuyerRole.B2B_HORECA)
                if (
                    actual_lead != expected_lead
                    or actual_intent != expected_intent
                    or actual_role != expected_role
                ):
                    mismatches.append(case_id)

        return LeadEvaluationReport(
            scenario_count=scenario_count,
            lead_precision=self._ratio(true_positive, true_positive + false_positive),
            lead_recall=self._ratio(true_positive, true_positive + false_negative),
            intent_accuracy=self._ratio(intent_matches, scenario_count),
            buyer_role_accuracy=self._ratio(role_matches, scenario_count),
            hot_false_positive_rate=self._ratio(hot_false_positives, non_lead_count),
            b2b_precision=self._ratio(correct_b2b, predicted_b2b),
            mismatch_ids=tuple(mismatches),
        )

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 1.0
