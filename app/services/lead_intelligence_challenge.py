from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.schemas.leads import BuyerRole, Intent
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer


@dataclass(frozen=True, slots=True)
class LanguageScore:
    language: str
    cases: int
    lead_accuracy: float
    intent_accuracy: float
    role_accuracy: float


@dataclass(frozen=True, slots=True)
class ConfusionCell:
    expected: str
    predicted: str
    count: int


@dataclass(frozen=True, slots=True)
class ChallengeMismatch:
    case_id: str
    language: str
    comment: str
    expected: str
    predicted: str


@dataclass(frozen=True, slots=True)
class LeadChallengeReport:
    dataset_version: str
    scenario_count: int
    lead_precision: float
    lead_recall: float
    intent_accuracy: float
    buyer_role_accuracy: float
    hot_false_positive_rate: float
    b2b_precision: float
    language_scores: tuple[LanguageScore, ...]
    intent_confusion: tuple[ConfusionCell, ...]
    mismatches: tuple[ChallengeMismatch, ...]

    @property
    def passed(self) -> bool:
        return (
            self.scenario_count >= 36
            and self.lead_precision >= 0.90
            and self.lead_recall >= 0.90
            and self.intent_accuracy >= 0.80
            and self.buyer_role_accuracy >= 0.80
            and self.hot_false_positive_rate <= 0.05
            and self.b2b_precision >= 0.85
        )


class LeadIntelligenceChallenge:
    """Frozen multilingual challenge evaluation with no DB or provider access."""

    DATASET_VERSION = "challenge:v1"

    def __init__(
        self,
        fixture_path: str | Path | None = None,
    ) -> None:
        self.fixture_path = (
            Path(fixture_path)
            if fixture_path is not None
            else Path(__file__).resolve().parents[2]
            / "fixtures"
            / "lead_intelligence_challenge_v1.json"
        )
        self.analyzer = RuleBasedLeadAnalyzer()

    def evaluate(self, *, hot_threshold: int = 70) -> LeadChallengeReport:
        cases = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        true_positive = false_positive = false_negative = 0
        intent_matches = role_matches = 0
        non_lead_count = hot_false_positives = 0
        predicted_b2b = correct_b2b = 0
        language_counts: dict[str, list[int]] = {}
        confusion: dict[tuple[str, str], int] = {}
        mismatches: list[ChallengeMismatch] = []

        for case in cases:
            expected_lead = bool(case["lead"])
            expected_intent = Intent(case["intent"])
            expected_role = BuyerRole(case["role"])
            language = str(case["language"])
            analysis = self.analyzer.classify(
                LeadAnalysisContext(
                    competitor="challenge-source",
                    post_caption=str(case["caption"]),
                    comment=str(case["comment"]),
                    username=f"challenge_{case['id']}",
                    previous_signals=[],
                    previous_interests=[],
                    evidence_ids=[len(language_counts) + 1],
                )
            )
            actual_lead = bool(analysis and analysis.is_lead)
            actual_intent = analysis.intent if analysis else Intent.OTHER
            actual_role = analysis.buyer_role if analysis else BuyerRole.UNKNOWN
            actual_score = analysis.lead_score if analysis else 0

            true_positive += int(expected_lead and actual_lead)
            false_positive += int(not expected_lead and actual_lead)
            false_negative += int(expected_lead and not actual_lead)
            intent_match = actual_intent == expected_intent
            role_match = actual_role == expected_role
            intent_matches += int(intent_match)
            role_matches += int(role_match)
            if not expected_lead:
                non_lead_count += 1
                hot_false_positives += int(actual_score >= hot_threshold)
            if actual_role == BuyerRole.B2B_HORECA:
                predicted_b2b += 1
                correct_b2b += int(expected_role == BuyerRole.B2B_HORECA)

            language_bucket = language_counts.setdefault(language, [0, 0, 0, 0])
            language_bucket[0] += 1
            language_bucket[1] += int(actual_lead == expected_lead)
            language_bucket[2] += int(intent_match)
            language_bucket[3] += int(role_match)
            confusion_key = (expected_intent.value, actual_intent.value)
            confusion[confusion_key] = confusion.get(confusion_key, 0) + 1

            if (
                actual_lead != expected_lead
                or not intent_match
                or not role_match
            ):
                mismatches.append(
                    ChallengeMismatch(
                        case_id=str(case["id"]),
                        language=language,
                        comment=str(case["comment"]),
                        expected=(
                            f"{'LEAD' if expected_lead else 'NO_LEAD'} / "
                            f"{expected_intent.value} / {expected_role.value}"
                        ),
                        predicted=(
                            f"{'LEAD' if actual_lead else 'NO_LEAD'} / "
                            f"{actual_intent.value} / {actual_role.value}"
                        ),
                    )
                )

        scenario_count = len(cases)
        language_scores = tuple(
            LanguageScore(
                language=language,
                cases=values[0],
                lead_accuracy=self._ratio(values[1], values[0]),
                intent_accuracy=self._ratio(values[2], values[0]),
                role_accuracy=self._ratio(values[3], values[0]),
            )
            for language, values in sorted(language_counts.items())
        )
        intent_confusion = tuple(
            ConfusionCell(expected=expected, predicted=predicted, count=count)
            for (expected, predicted), count in sorted(
                confusion.items(), key=lambda item: (-item[1], item[0])
            )
            if expected != predicted
        )
        return LeadChallengeReport(
            dataset_version=self.DATASET_VERSION,
            scenario_count=scenario_count,
            lead_precision=self._ratio(true_positive, true_positive + false_positive),
            lead_recall=self._ratio(true_positive, true_positive + false_negative),
            intent_accuracy=self._ratio(intent_matches, scenario_count),
            buyer_role_accuracy=self._ratio(role_matches, scenario_count),
            hot_false_positive_rate=self._ratio(hot_false_positives, non_lead_count),
            b2b_precision=self._ratio(correct_b2b, predicted_b2b),
            language_scores=language_scores,
            intent_confusion=intent_confusion,
            mismatches=tuple(mismatches),
        )

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 1.0
