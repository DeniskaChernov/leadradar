"""Ежедневный quality digest для Telegram admin."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AIFeedback, Comment, Lead, LeadStatus
from app.services.signal_recency import fresh_signal_clause


@dataclass(frozen=True, slots=True)
class DailyQualitySnapshot:
    report_date: date
    new_leads: int
    not_lead: int
    hot_leads: int
    hot_false_positives: int
    reviewed_feedback: int
    stale_rules_count: int
    openai_events: int


class QualityReportService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
        rules_version: str,
        signal_max_age_days: int = 30,
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold
        self.rules_version = rules_version
        self.signal_max_age_days = signal_max_age_days

    async def build_snapshot(
        self,
        *,
        report_date: date | None = None,
        timezone_name: str = "UTC",
    ) -> DailyQualitySnapshot:
        tz = ZoneInfo(timezone_name)
        report_date = report_date or datetime.now(tz).date()
        day_start = datetime.combine(report_date, datetime.min.time(), tzinfo=tz).astimezone(UTC)
        day_end = day_start + timedelta(days=1)
        async with self.session_factory() as session:
            new_leads = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.created_at >= day_start,
                        Lead.created_at < day_end,
                        Lead.status == LeadStatus.NEW,
                    )
                )
                or 0
            )
            not_lead = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.updated_at >= day_start,
                        Lead.updated_at < day_end,
                        Lead.status == LeadStatus.NOT_LEAD,
                    )
                )
                or 0
            )
            hot_leads = int(
                await session.scalar(
                    select(func.count(Lead.id)).where(
                        Lead.created_at >= day_start,
                        Lead.created_at < day_end,
                        Lead.lead_score >= self.hot_threshold,
                        Lead.status != LeadStatus.NOT_LEAD,
                    )
                )
                or 0
            )
            hot_false_positives = int(
                await session.scalar(
                    select(func.count(AIFeedback.id)).where(
                        AIFeedback.manager_is_lead.is_(False),
                        AIFeedback.predicted_score >= self.hot_threshold,
                        AIFeedback.updated_at >= day_start,
                        AIFeedback.updated_at < day_end,
                    )
                )
                or 0
            )
            reviewed_feedback = int(
                await session.scalar(
                    select(func.count(AIFeedback.id)).where(
                        AIFeedback.manager_is_lead.is_not(None),
                        AIFeedback.updated_at >= day_start,
                        AIFeedback.updated_at < day_end,
                    )
                )
                or 0
            )
            stale_rules = 0
            # JOIN обязателен: fresh_signal_clause фильтрует Comment (без него — cartesian product).
            actionable = (
                await session.execute(
                    select(Lead.analysis_details)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .where(
                        Lead.status.in_(
                            [
                                LeadStatus.NEW,
                                LeadStatus.AI_PENDING,
                                LeadStatus.ANALYZING,
                            ]
                        ),
                        fresh_signal_clause(max_age_days=self.signal_max_age_days),
                    )
                )
            ).scalars()
            for details in actionable:
                if not isinstance(details, dict) or details.get("rules_version") != self.rules_version:
                    stale_rules += 1
            openai_events = int(
                await session.scalar(
                    select(func.count(AIFeedback.id)).where(
                        AIFeedback.created_at >= day_start,
                        AIFeedback.created_at < day_end,
                    )
                )
                or 0
            )
        return DailyQualitySnapshot(
            report_date=report_date,
            new_leads=new_leads,
            not_lead=not_lead,
            hot_leads=hot_leads,
            hot_false_positives=hot_false_positives,
            reviewed_feedback=reviewed_feedback,
            stale_rules_count=stale_rules,
            openai_events=openai_events,
        )

    @staticmethod
    def format_message(snapshot: DailyQualitySnapshot, *, rules_version: str) -> str:
        fp_rate = (
            f"{(snapshot.hot_false_positives / snapshot.reviewed_feedback * 100):.1f}%"
            if snapshot.reviewed_feedback
            else "—"
        )
        return (
            f"<b>Lead Radar · качество за {snapshot.report_date.isoformat()}</b>\n"
            f"Новых лидов: <b>{snapshot.new_leads}</b> · HOT: <b>{snapshot.hot_leads}</b>\n"
            f"NOT_LEAD за день: <b>{snapshot.not_lead}</b>\n"
            f"Отзывов менеджера: <b>{snapshot.reviewed_feedback}</b> · HOT→не лид: "
            f"<b>{snapshot.hot_false_positives}</b> ({fp_rate})\n"
            f"Без stamp правил {rules_version}: <b>{snapshot.stale_rules_count}</b>\n"
            f"Новых AIFeedback записей: <b>{snapshot.openai_events}</b>"
        )
