"""Read-only search results, exact creation provenance and unique customer cards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, and_, case, desc, func, or_, select

from app.db.models import (
    Comment,
    Competitor,
    Contact,
    Lead,
    LeadStatus,
    MonitorRun,
    SearchResultOrigin,
)
from app.services.assortment_policy import assortment_eligible_clause

PENDING = (LeadStatus.ANALYZING, LeadStatus.AI_PENDING)


@dataclass(frozen=True, slots=True)
class SearchScope:
    run: MonitorRun
    next_start: datetime | None

    @property
    def exact(self) -> bool:
        return self.run.result_tracking_version == 1

    def creation_clause(self, *, comments: bool):
        if self.exact:
            origin = SearchResultOrigin.discovered_run_id if comments else SearchResultOrigin.lead_run_id
            return Comment.id.in_(select(SearchResultOrigin.comment_id).where(origin == self.run.id))
        # Old scans predate provenance. Never include a later scan, even if an
        # interrupted run was finalized only after that later scan had ended.
        timestamp = Comment.discovered_at if comments else Lead.created_at
        bounds = [timestamp >= self.run.started_at, timestamp <= (self.run.completed_at or datetime.now(UTC))]
        if self.next_start is not None:
            bounds.append(timestamp < self.next_start)
        return and_(*bounds)

    def comment_ids(self, *, comments: bool):
        statement = select(Comment.id).outerjoin(Lead, Lead.comment_id == Comment.id)
        if not comments:
            statement = statement.where(Lead.status != LeadStatus.NOT_LEAD)
        return statement.where(self.creation_clause(comments=comments))


def unique_customer_cards(statement: Select, *, per_post: bool = False) -> Select:
    """Choose one deterministic representative after filters; retain all evidence."""
    ranked = statement.order_by(None).with_only_columns(
        Comment.id.label("comment_id"),
        func.row_number().over(
            partition_by=(Contact.id, Comment.post_id) if per_post else Contact.id,
            order_by=(
                case((Lead.status.in_(PENDING), 1), else_=0),
                desc(func.coalesce(Lead.lead_score, 0)),
                desc(Comment.discovered_at), desc(Comment.id),
            ),
        ).label("position"),
    ).subquery()
    return statement.where(Comment.id.in_(select(ranked.c.comment_id).where(ranked.c.position == 1)))


class SearchResultsService:
    def __init__(self, session_factory, hot_threshold: int):
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def load(self, run_id: int) -> SearchScope | None:
        async with self.session_factory() as session:
            run = await session.get(MonitorRun, run_id)
            if run is None:
                return None
            next_start = await session.scalar(select(func.min(MonitorRun.started_at)).where(or_(
                MonitorRun.started_at > run.started_at,
                (MonitorRun.started_at == run.started_at) & (MonitorRun.id > run.id),
            )))
            return SearchScope(run, next_start)

    async def summary(self, scope: SearchScope, *, vertical: str) -> dict:
        async with self.session_factory() as session:
            comments = await session.scalar(select(func.count(Comment.id)).join(
                Competitor, Competitor.id == Comment.competitor_id,
            ).where(scope.creation_clause(comments=True), Competitor.vertical == vertical))
            statement = select(
                func.count(Lead.id).label("signals"),
                func.count(func.distinct(Lead.contact_id)).label("people"),
                func.count(func.distinct(case((Lead.status.in_(PENDING), Lead.contact_id)))).label("pending"),
                func.count(func.distinct(case((
                    (Lead.lead_score >= self.hot_threshold) & assortment_eligible_clause(Lead)
                    & Lead.status.not_in(PENDING), Lead.contact_id,
                )))).label("hot"),
            ).select_from(Lead).join(Comment, Comment.id == Lead.comment_id).join(
                Competitor, Competitor.id == Comment.competitor_id,
            ).where(scope.creation_clause(comments=False), Lead.status != LeadStatus.NOT_LEAD,
                    Competitor.vertical == vertical)
            counts = (await session.execute(statement)).one()
        return {"comments": int(comments or 0), "people": counts.people, "pending": counts.pending,
                "hot": counts.hot, "repeated_cards": counts.signals - counts.people}

    async def companies(self, scope: SearchScope, *, vertical: str) -> list:
        async with self.session_factory() as session:
            return list((await session.execute(select(
                Competitor,
                func.count(func.distinct(Comment.contact_id)).label("people"),
                func.count(func.distinct(Comment.post_id)).label("posts"),
                func.count(Comment.id).label("comments"),
            ).join(Comment, Comment.competitor_id == Competitor.id).where(
                Competitor.vertical == vertical, Comment.id.in_(scope.comment_ids(comments=False)),
            ).group_by(Competitor.id).order_by(Competitor.normalized_handle))).all())
