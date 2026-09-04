"""Независимые quality gates: unseen lead / audience / rattan + reproducible metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.schemas.leads import Intent
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.audience_membership_unseen_cases import (
    AUDIENCE_MEMBERSHIP_UNSEEN_CASES,
    AudienceMembershipUnseenCase,
    AudienceProfileSpec,
)
from app.services.audience_registry import AUDIENCE_BY_SLUG
from app.services.audience_service import AudienceEngine
from app.services.lead_intelligence_challenge import ConfusionCell
from app.services.offline_pilot_service import BinaryMetrics
from app.services.rattan_taxonomy_service import RattanTaxonomyService


@dataclass(frozen=True, slots=True)
class GateMismatch:
    case_id: str
    expected: str
    predicted: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class QualityGateReport:
    gate_id: str
    label: str
    dataset_version: str
    case_count: int
    labeled_decisions: int
    metrics: BinaryMetrics
    intent_accuracy: float | None
    layer_accuracy: float | None
    f1: float
    confusion: tuple[ConfusionCell, ...]
    mismatches: tuple[GateMismatch, ...]

    @property
    def precision(self) -> float:
        return self.metrics.precision

    @property
    def recall(self) -> float:
        return self.metrics.recall

    @property
    def accuracy(self) -> float:
        return self.metrics.accuracy

    @property
    def passed(self) -> bool:
        if self.gate_id == "lead_unseen":
            return (
                self.case_count >= 50
                and self.precision >= 0.85
                and self.recall >= 0.85
                and (self.intent_accuracy or 0.0) >= 0.80
            )
        if self.gate_id == "rattan_unseen":
            return (
                self.case_count >= 30
                and self.precision >= 0.95
                and self.recall >= 0.95
                and (self.layer_accuracy or 0.0) >= 0.90
            )
        if self.gate_id == "audience_unseen":
            return self.labeled_decisions >= 160 and self.accuracy >= 0.90
        return False


@dataclass(frozen=True, slots=True)
class IndependentQualityGatesSnapshot:
    generated_at: datetime
    rules_version: str
    lead_unseen: QualityGateReport
    rattan_unseen: QualityGateReport
    audience_unseen: QualityGateReport
    calibration_cases: int
    challenge_cases: int
    robustness_cases: int

    @property
    def passed(self) -> bool:
        return (
            self.lead_unseen.passed
            and self.rattan_unseen.passed
            and self.audience_unseen.passed
        )

    def openai_live_allowed(self) -> tuple[bool, str]:
        """После смены rules_version live GPT разрешён только при PASS unseen gates."""
        if self.passed:
            return True, ""
        blocked = [
            gate.label
            for gate in (self.lead_unseen, self.rattan_unseen, self.audience_unseen)
            if not gate.passed
        ]
        return (
            False,
            "Unseen quality gates не пройдены для правил "
            f"{self.rules_version}: {', '.join(blocked)}. "
            "Исправьте классификатор и прогоните pytest перед arm OpenAI.",
        )


class IndependentQualityGatesService:
    """Оффлайн-оценка независимых наборов без БД и внешних вызовов."""

    LEAD_DATASET = "unseen:v1"
    RATTAN_DATASET = "unseen:v1"
    AUDIENCE_DATASET = "unseen:v2"

    def __init__(self, fixtures_dir: str | Path = "fixtures") -> None:
        self.fixtures_dir = Path(fixtures_dir)
        self.lead_analyzer = RuleBasedLeadAnalyzer()

    def snapshot(self, *, rules_version: str = "3.2") -> IndependentQualityGatesSnapshot:
        now = datetime.now(UTC)
        lead_unseen = self.evaluate_lead_unseen()
        rattan_unseen = self.evaluate_rattan_unseen()
        audience_unseen = self.evaluate_audience_unseen()
        calibration_cases = len(self._load_json("lead_intelligence_v3_eval.json"))
        challenge_cases = len(self._load_json("lead_intelligence_challenge_v1.json"))
        robustness_cases = len(self._load_json("golden_lead_calibration.json")) + len(
            self._load_json("rattan_vertical_v2_golden.json")
        )
        return IndependentQualityGatesSnapshot(
            generated_at=now,
            rules_version=(rules_version or "3.2").strip() or "3.2",
            lead_unseen=lead_unseen,
            rattan_unseen=rattan_unseen,
            audience_unseen=audience_unseen,
            calibration_cases=calibration_cases,
            challenge_cases=challenge_cases,
            robustness_cases=robustness_cases,
        )

    def evaluate_lead_unseen(self) -> QualityGateReport:
        rows = self._load_json("lead_intelligence_unseen_v1.json")
        expected_flags: list[bool] = []
        actual_flags: list[bool] = []
        intent_matches: list[bool] = []
        confusion: dict[tuple[str, str], int] = {}
        mismatches: list[GateMismatch] = []

        for row in rows:
            case_id = str(row["id"])
            expected_lead = bool(row["expected_is_lead"])
            expected_intent = str(row["expected_intent"])
            analysis = self.lead_analyzer.classify(
                LeadAnalysisContext(
                    competitor="unseen-gate",
                    post_caption=str(row.get("caption") or ""),
                    comment=str(row["comment"]),
                    username=f"unseen_{case_id}",
                    previous_signals=[],
                    previous_interests=[],
                )
            )
            actual_lead = bool(analysis and analysis.is_lead)
            actual_intent = analysis.intent.value if analysis else Intent.OTHER.value
            expected_flags.append(expected_lead)
            actual_flags.append(actual_lead)
            intent_match = actual_intent == expected_intent
            intent_matches.append(intent_match)
            confusion[(expected_intent, actual_intent)] = (
                confusion.get((expected_intent, actual_intent), 0) + 1
            )
            if actual_lead != expected_lead or not intent_match:
                mismatches.append(
                    GateMismatch(
                        case_id=case_id,
                        expected=f"{'LEAD' if expected_lead else 'NO_LEAD'} / {expected_intent}",
                        predicted=f"{'LEAD' if actual_lead else 'NO_LEAD'} / {actual_intent}",
                        detail=str(row["comment"]),
                    )
                )

        metrics = self._binary_metrics(expected_flags, actual_flags)
        return QualityGateReport(
            gate_id="lead_unseen",
            label="Lead intelligence · unseen",
            dataset_version=self.LEAD_DATASET,
            case_count=len(rows),
            labeled_decisions=len(rows),
            metrics=metrics,
            intent_accuracy=self._ratio(intent_matches),
            layer_accuracy=None,
            f1=self._f1(metrics),
            confusion=self._confusion_cells(confusion),
            mismatches=tuple(mismatches),
        )

    def evaluate_rattan_unseen(self) -> QualityGateReport:
        rows = self._load_json("rattan_unseen_v1.json")
        expected_flags: list[bool] = []
        actual_flags: list[bool] = []
        layer_matches: list[bool] = []
        mismatches: list[GateMismatch] = []

        for index, row in enumerate(rows):
            case_id = f"rattan-unseen:{index}"
            expected_rattan = bool(row["is_rattan"])
            expected_layer = str(row["layer"])
            result = RattanTaxonomyService.classify(str(row["text"]))
            actual_rattan = result.is_rattan
            expected_flags.append(expected_rattan)
            actual_flags.append(actual_rattan)
            layer_matches.append(result.layer.value == expected_layer)
            if actual_rattan != expected_rattan or result.layer.value != expected_layer:
                mismatches.append(
                    GateMismatch(
                        case_id=case_id,
                        expected=f"rattan={expected_rattan} / {expected_layer}",
                        predicted=f"rattan={actual_rattan} / {result.layer.value}",
                        detail=str(row["text"]),
                    )
                )

        metrics = self._binary_metrics(expected_flags, actual_flags)
        return QualityGateReport(
            gate_id="rattan_unseen",
            label="Rattan taxonomy · unseen",
            dataset_version=self.RATTAN_DATASET,
            case_count=len(rows),
            labeled_decisions=len(rows),
            metrics=metrics,
            intent_accuracy=None,
            layer_accuracy=self._ratio(layer_matches),
            f1=self._f1(metrics),
            confusion=(),
            mismatches=tuple(mismatches),
        )

    def evaluate_audience_unseen(self) -> QualityGateReport:
        expected_flags: list[bool] = []
        actual_flags: list[bool] = []
        mismatches: list[GateMismatch] = []
        last_seen = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)

        for case in AUDIENCE_MEMBERSHIP_UNSEEN_CASES:
            facts = self._build_audience_facts(case, last_seen)
            for slug, expected_active in case.expected.items():
                definition = AUDIENCE_BY_SLUG.get(slug)
                if definition is None:
                    raise KeyError(f"Unknown audience slug in unseen gate: {slug}")
                # Как в AudienceEngine.sync: vertical из registry входит в criteria_json.
                criteria = {**definition.criteria, "vertical": definition.vertical}
                active, _, _, _ = AudienceEngine._evaluate(
                    criteria,
                    facts,
                    last_seen,
                )
                expected_flags.append(bool(expected_active))
                actual_flags.append(bool(active))
                if bool(active) != bool(expected_active):
                    mismatches.append(
                        GateMismatch(
                            case_id=f"{case.case_id}:{slug}",
                            expected="ACTIVE" if expected_active else "INACTIVE",
                            predicted="ACTIVE" if active else "INACTIVE",
                        )
                    )

        metrics = self._binary_metrics(expected_flags, actual_flags)
        return QualityGateReport(
            gate_id="audience_unseen",
            label="Audience membership · unseen",
            dataset_version=self.AUDIENCE_DATASET,
            case_count=len(AUDIENCE_MEMBERSHIP_UNSEEN_CASES),
            labeled_decisions=len(expected_flags),
            metrics=metrics,
            intent_accuracy=None,
            layer_accuracy=None,
            f1=self._f1(metrics),
            confusion=(),
            mismatches=tuple(mismatches),
        )

    def _build_audience_facts(
        self,
        case: AudienceMembershipUnseenCase,
        last_seen: datetime,
    ) -> dict[str, Any]:
        profiles = {
            (profile.dimension, profile.topic): self._profile_object(profile, last_seen)
            for profile in case.profiles
        }
        ages = case.source_ages_days or tuple(5 for _ in case.source_competitors)
        source_observations = [
            SimpleNamespace(
                competitor_id=competitor_id,
                evidence_id=index + 1,
                observed_at=last_seen - timedelta(days=age_days),
            )
            for index, (competitor_id, age_days) in enumerate(
                zip(case.source_competitors, ages, strict=False)
            )
        ]
        facts = dict(case.facts)
        facts["profiles"] = profiles
        facts["source_observations"] = source_observations
        facts["products"] = set(facts.get("products") or ())
        facts["intents"] = set(facts.get("intents") or ())
        facts["rattan_layers"] = set(facts.get("rattan_layers") or ())
        facts["rattan_roles"] = set(facts.get("rattan_roles") or ())
        return facts

    @staticmethod
    def _profile_object(profile: AudienceProfileSpec, last_seen: datetime) -> SimpleNamespace:
        return SimpleNamespace(
            dimension=profile.dimension,
            topic=profile.topic,
            commercial_signal_count=profile.commercial_signal_count,
            current_score=profile.current_score,
            evidence_ids_json=list(profile.evidence_ids),
            last_seen_at=last_seen,
        )

    def _load_json(self, filename: str) -> list[dict[str, Any]]:
        path = self.fixtures_dir / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Fixture must be a list: {path}")
        return [row for row in payload if isinstance(row, dict)]

    @staticmethod
    def _binary_metrics(expected: list[bool], actual: list[bool]) -> BinaryMetrics:
        pairs = list(zip(expected, actual, strict=True))
        return BinaryMetrics(
            true_positive=sum(wanted and got for wanted, got in pairs),
            true_negative=sum(not wanted and not got for wanted, got in pairs),
            false_positive=sum(not wanted and got for wanted, got in pairs),
            false_negative=sum(wanted and not got for wanted, got in pairs),
        )

    @staticmethod
    def _ratio(values: list[bool]) -> float:
        return sum(values) / len(values) if values else 1.0

    @staticmethod
    def _f1(metrics: BinaryMetrics) -> float:
        precision = metrics.precision
        recall = metrics.recall
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    @staticmethod
    def _confusion_cells(confusion: dict[tuple[str, str], int]) -> tuple[ConfusionCell, ...]:
        return tuple(
            ConfusionCell(expected=expected, predicted=predicted, count=count)
            for (expected, predicted), count in sorted(
                confusion.items(),
                key=lambda item: (-item[1], item[0]),
            )
            if expected != predicted
        )
