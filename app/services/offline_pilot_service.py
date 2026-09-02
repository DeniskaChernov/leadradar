from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Comment, Evidence, PublicSignal
from app.schemas.instagram import InstagramComment, InstagramPost
from app.services.ai_service import LeadAnalysisContext, RuleBasedLeadAnalyzer
from app.services.contact_service import ContactService
from app.services.rattan_taxonomy_service import RattanTaxonomyService


@dataclass(frozen=True, slots=True)
class PilotCase:
    case_id: str
    family: str
    comment: str
    caption: str
    expected_is_lead: bool | None = None
    expected_intent: str | None = None
    expected_is_rattan: bool | None = None
    expected_layer: str | None = None
    defer_to_openai: bool = False


@dataclass(frozen=True, slots=True)
class BinaryMetrics:
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int

    @property
    def total(self) -> int:
        return self.true_positive + self.true_negative + self.false_positive + self.false_negative

    @property
    def precision(self) -> float:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else 1.0

    @property
    def recall(self) -> float:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else 1.0

    @property
    def accuracy(self) -> float:
        return (self.true_positive + self.true_negative) / self.total if self.total else 1.0


@dataclass(frozen=True, slots=True)
class IngestionIdempotency:
    first_created: int
    retry_created: int
    comments: int
    public_signals: int
    evidence: int

    @property
    def duplicate_records(self) -> int:
        return max(0, self.comments - self.first_created) + max(
            0, self.public_signals - self.first_created
        ) + max(0, self.evidence - self.first_created)


@dataclass(frozen=True, slots=True)
class OfflinePilotReport:
    corpus_size: int
    lead_cases: int
    rattan_cases: int
    lead_metrics: BinaryMetrics
    lead_intent_accuracy: float
    rattan_metrics: BinaryMetrics
    rattan_layer_accuracy: float
    deterministic_digest: str
    lead_false_positive_ids: tuple[str, ...]
    lead_false_negative_ids: tuple[str, ...]
    lead_intent_mismatch_ids: tuple[str, ...]
    rattan_false_positive_ids: tuple[str, ...]
    rattan_false_negative_ids: tuple[str, ...]
    rattan_layer_mismatch_ids: tuple[str, ...]
    ingestion: IngestionIdempotency | None = None

    @property
    def passed(self) -> bool:
        ingestion_ok = self.ingestion is None or (
            self.ingestion.retry_created == 0 and self.ingestion.duplicate_records == 0
        )
        return (
            self.corpus_size >= 500
            and self.lead_metrics.precision >= 0.95
            and self.lead_metrics.recall >= 0.95
            and self.lead_intent_accuracy >= 0.90
            and self.rattan_metrics.precision >= 0.98
            and self.rattan_metrics.recall >= 0.98
            and self.rattan_layer_accuracy >= 0.98
            and ingestion_ok
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lead_metrics"].update(
            precision=self.lead_metrics.precision,
            recall=self.lead_metrics.recall,
            accuracy=self.lead_metrics.accuracy,
        )
        payload["rattan_metrics"].update(
            precision=self.rattan_metrics.precision,
            recall=self.rattan_metrics.recall,
            accuracy=self.rattan_metrics.accuracy,
        )
        if self.ingestion is not None:
            payload["ingestion"]["duplicate_records"] = self.ingestion.duplicate_records
        payload["passed"] = self.passed
        return payload


class OfflinePilotService:
    """Run a deterministic, network-free robustness pilot over labeled fixtures."""

    VARIANTS = (
        lambda value: value,
        lambda value: value.lower(),
        lambda value: value.upper(),
        lambda value: f" {value} ",
        lambda value: f"{value}?",
        lambda value: f"{value}!",
        lambda value: f"{value} 🙏",
        lambda value: f"{value}...",
        lambda value: " ".join(value.split()),
        lambda value: f"{value}  ",
    )

    def __init__(self, fixtures_dir: str | Path = "fixtures") -> None:
        self.fixtures_dir = Path(fixtures_dir)
        self.lead_analyzer = RuleBasedLeadAnalyzer()

    def build_corpus(self) -> list[PilotCase]:
        lead_rows = self._load_json("golden_lead_calibration.json")
        rattan_rows = self._load_json("rattan_vertical_v2_golden.json")
        cases: list[PilotCase] = []
        for row in lead_rows:
            for variant_index, transform in enumerate(self.VARIANTS):
                cases.append(
                    PilotCase(
                        case_id=f"lead:{row['id']}:{variant_index}",
                        family="lead",
                        comment=transform(str(row["comment"])),
                        caption=str(row.get("post_caption") or ""),
                        expected_is_lead=bool(row["expected_is_lead"]),
                        expected_intent=str(row["expected_intent"]),
                        defer_to_openai=bool(row.get("defer_to_openai")),
                    )
                )
        for row_index, row in enumerate(rattan_rows):
            for variant_index, transform in enumerate(self.VARIANTS):
                cases.append(
                    PilotCase(
                        case_id=f"rattan:{row_index}:{variant_index}",
                        family="rattan",
                        comment=transform(str(row["text"])),
                        caption="",
                        expected_is_rattan=bool(row["is_rattan"]),
                        expected_layer=str(row["layer"]),
                    )
                )
        return cases

    def evaluate(self, cases: list[PilotCase] | None = None) -> OfflinePilotReport:
        corpus = cases or self.build_corpus()
        lead_expected: list[bool] = []
        lead_actual: list[bool] = []
        intent_matches: list[bool] = []
        rattan_expected: list[bool] = []
        rattan_actual: list[bool] = []
        layer_matches: list[bool] = []
        predictions: list[dict[str, Any]] = []
        lead_false_positive_ids: list[str] = []
        lead_false_negative_ids: list[str] = []
        lead_intent_mismatch_ids: list[str] = []
        rattan_false_positive_ids: list[str] = []
        rattan_false_negative_ids: list[str] = []
        rattan_layer_mismatch_ids: list[str] = []

        for case in corpus:
            if case.family == "lead":
                result = self.lead_analyzer.classify(
                    LeadAnalysisContext(
                        competitor="offline-pilot",
                        post_caption=case.caption,
                        comment=case.comment,
                        username="offline_pilot",
                        previous_signals=[],
                        previous_interests=[],
                    )
                )
                if case.defer_to_openai:
                    assert result is None, case.case_id
                    predictions.append({"id": case.case_id, "deferred": True})
                    continue
                actual_is_lead = bool(result and result.is_lead)
                actual_intent = result.intent.value if result else "OTHER"
                lead_expected.append(bool(case.expected_is_lead))
                lead_actual.append(actual_is_lead)
                intent_matches.append(actual_intent == case.expected_intent)
                if actual_is_lead and not case.expected_is_lead:
                    lead_false_positive_ids.append(case.case_id)
                if case.expected_is_lead and not actual_is_lead:
                    lead_false_negative_ids.append(case.case_id)
                if actual_intent != case.expected_intent:
                    lead_intent_mismatch_ids.append(case.case_id)
                predictions.append(
                    {
                        "id": case.case_id,
                        "is_lead": actual_is_lead,
                        "intent": actual_intent,
                    }
                )
            else:
                result = RattanTaxonomyService.classify(case.comment)
                rattan_expected.append(bool(case.expected_is_rattan))
                rattan_actual.append(result.is_rattan)
                layer_matches.append(result.layer.value == case.expected_layer)
                if result.is_rattan and not case.expected_is_rattan:
                    rattan_false_positive_ids.append(case.case_id)
                if case.expected_is_rattan and not result.is_rattan:
                    rattan_false_negative_ids.append(case.case_id)
                if result.layer.value != case.expected_layer:
                    rattan_layer_mismatch_ids.append(case.case_id)
                predictions.append(
                    {
                        "id": case.case_id,
                        "is_rattan": result.is_rattan,
                        "layer": result.layer.value,
                    }
                )

        digest_payload = json.dumps(predictions, sort_keys=True, ensure_ascii=False)
        return OfflinePilotReport(
            corpus_size=len(corpus),
            lead_cases=sum(1 for case in corpus if case.family == "lead"),
            rattan_cases=len(rattan_expected),
            lead_metrics=self._binary_metrics(lead_expected, lead_actual),
            lead_intent_accuracy=self._ratio(intent_matches),
            rattan_metrics=self._binary_metrics(rattan_expected, rattan_actual),
            rattan_layer_accuracy=self._ratio(layer_matches),
            deterministic_digest=hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
            lead_false_positive_ids=tuple(lead_false_positive_ids),
            lead_false_negative_ids=tuple(lead_false_negative_ids),
            lead_intent_mismatch_ids=tuple(lead_intent_mismatch_ids),
            rattan_false_positive_ids=tuple(rattan_false_positive_ids),
            rattan_false_negative_ids=tuple(rattan_false_negative_ids),
            rattan_layer_mismatch_ids=tuple(rattan_layer_mismatch_ids),
        )

    async def verify_ingestion_idempotency(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cases: list[PilotCase] | None = None,
    ) -> IngestionIdempotency:
        corpus = cases or self.build_corpus()
        contact_service = ContactService(session_factory)
        first_created = 0
        retry_created = 0
        for replay_index in range(2):
            for index, case in enumerate(corpus):
                post, comment = self._instagram_payload(case, index)
                persisted = await contact_service.persist_signal(post, comment)
                if persisted.created:
                    if replay_index == 0:
                        first_created += 1
                    else:
                        retry_created += 1

        async with session_factory() as session:
            comments = int(await session.scalar(select(func.count(Comment.id))) or 0)
            public_signals = int(
                await session.scalar(select(func.count(PublicSignal.id))) or 0
            )
            evidence = int(await session.scalar(select(func.count(Evidence.id))) or 0)
        return IngestionIdempotency(
            first_created=first_created,
            retry_created=retry_created,
            comments=comments,
            public_signals=public_signals,
            evidence=evidence,
        )

    @staticmethod
    def with_ingestion(
        report: OfflinePilotReport, ingestion: IngestionIdempotency
    ) -> OfflinePilotReport:
        return OfflinePilotReport(
            corpus_size=report.corpus_size,
            lead_cases=report.lead_cases,
            rattan_cases=report.rattan_cases,
            lead_metrics=report.lead_metrics,
            lead_intent_accuracy=report.lead_intent_accuracy,
            rattan_metrics=report.rattan_metrics,
            rattan_layer_accuracy=report.rattan_layer_accuracy,
            deterministic_digest=report.deterministic_digest,
            lead_false_positive_ids=report.lead_false_positive_ids,
            lead_false_negative_ids=report.lead_false_negative_ids,
            lead_intent_mismatch_ids=report.lead_intent_mismatch_ids,
            rattan_false_positive_ids=report.rattan_false_positive_ids,
            rattan_false_negative_ids=report.rattan_false_negative_ids,
            rattan_layer_mismatch_ids=report.rattan_layer_mismatch_ids,
            ingestion=ingestion,
        )

    def _load_json(self, filename: str) -> list[dict[str, Any]]:
        path = self.fixtures_dir / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Offline pilot fixture must be a list: {path}")
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
    def _instagram_payload(
        case: PilotCase, index: int
    ) -> tuple[InstagramPost, InstagramComment]:
        created_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)
        suffix = f"{index:04d}"
        post = InstagramPost(
            platform_post_id=f"offline-pilot-post-{suffix}",
            competitor="offline-pilot",
            url=f"https://www.instagram.com/p/offline-pilot-{suffix}/",
            caption=case.caption,
            comments_count=1,
            published_at=created_at,
            raw_data={"source": "offline_pilot", "case_id": case.case_id},
        )
        comment = InstagramComment(
            platform_comment_id=f"offline-pilot-comment-{suffix}",
            platform_user_id=f"offline-pilot-user-{suffix}",
            username=f"offline_pilot_{suffix}",
            profile_url=f"https://www.instagram.com/offline_pilot_{suffix}/",
            text=case.comment,
            created_at=created_at,
            raw_data={"source": "offline_pilot", "case_id": case.case_id},
        )
        return post, comment
