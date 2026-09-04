"""Агрегация manager feedback для offline-улучшения rule-based классификации."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AIFeedback, Lead, LeadStatus


@dataclass(frozen=True, slots=True)
class FeedbackPatternRow:
    comment_preview: str
    predicted_score: int
    predicted_intent: str
    product_category: str | None
    lead_id: int
    marked_at: datetime


class FeedbackLearningService:
    """Собирает false-positive кейсы из AIFeedback без автоизменения правил в рантайме."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def false_positive_rows(self, *, limit: int = 20, days: int = 30) -> list[FeedbackPatternRow]:
        limit = max(1, min(limit, 100))
        started_at = datetime.now(UTC) - timedelta(days=max(1, days))
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        AIFeedback.lead_id,
                        AIFeedback.comment_text,
                        AIFeedback.predicted_score,
                        AIFeedback.predicted_intent,
                        AIFeedback.predicted_product,
                        AIFeedback.updated_at,
                    )
                    .where(
                        AIFeedback.manager_is_lead.is_(False),
                        AIFeedback.predicted_score >= self.hot_threshold,
                        AIFeedback.updated_at >= started_at,
                    )
                    .order_by(desc(AIFeedback.predicted_score), desc(AIFeedback.updated_at))
                    .limit(limit)
                )
            ).all()
        return [
            FeedbackPatternRow(
                lead_id=int(lead_id),
                comment_preview=(text or "")[:160],
                predicted_score=int(score or 0),
                predicted_intent=str(intent or ""),
                product_category=product,
                marked_at=marked_at or datetime.now(UTC),
            )
            for lead_id, text, score, intent, product, marked_at in rows
        ]

    async def snapshot(self, *, days: int = 30) -> dict[str, object]:
        started_at = datetime.now(UTC) - timedelta(days=max(1, days))
        async with self.session_factory() as session:
            hot_fp = int(
                await session.scalar(
                    select(func.count(AIFeedback.id)).where(
                        AIFeedback.manager_is_lead.is_(False),
                        AIFeedback.predicted_score >= self.hot_threshold,
                        AIFeedback.updated_at >= started_at,
                    )
                )
                or 0
            )
            reviewed = int(
                await session.scalar(
                    select(func.count(AIFeedback.id)).where(
                        AIFeedback.manager_is_lead.is_not(None),
                        AIFeedback.updated_at >= started_at,
                    )
                )
                or 0
            )
            intent_rows = (
                await session.execute(
                    select(AIFeedback.predicted_intent, func.count(AIFeedback.id))
                    .where(
                        AIFeedback.manager_is_lead.is_(False),
                        AIFeedback.updated_at >= started_at,
                    )
                    .group_by(AIFeedback.predicted_intent)
                    .order_by(desc(func.count(AIFeedback.id)))
                    .limit(5)
                )
            ).all()
            reopened = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.status != LeadStatus.NOT_LEAD,
                        Lead.updated_at >= started_at,
                        Lead.id.in_(
                            select(AIFeedback.lead_id).where(
                                AIFeedback.manager_is_lead.is_(False),
                                AIFeedback.updated_at >= started_at,
                            )
                        ),
                    )
                )
                or 0
            )
        return {
            "days": days,
            "reviewed": reviewed,
            "hot_false_positives": hot_fp,
            "top_intents": [
                {"intent": intent or "—", "count": int(count)} for intent, count in intent_rows
            ],
            "reopened_after_not_lead": reopened,
            "export_hint": "Добавьте кейсы в fixtures/lead_intelligence_v3_eval.json и bump lead_analysis_version",
        }

    async def export_cases(self, *, limit: int = 50, days: int = 30) -> list[dict[str, object]]:
        rows = await self.false_positive_rows(limit=limit, days=days)
        return [
            {
                "lead_id": row.lead_id,
                "comment": row.comment_preview,
                "predicted_score": row.predicted_score,
                "predicted_intent": row.predicted_intent,
                "product_category": row.product_category,
                "marked_at": row.marked_at.isoformat(),
            }
            for row in rows
        ]
