from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Post
from app.db.repositories import CompetitorRepository, PostRepository
from app.providers.base import InstagramProvider, ProviderError
from app.schemas.instagram import InstagramPost
from app.services.contact_service import ContactService
from app.services.lead_service import LeadService
from app.services.notification_service import LeadNotifier

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CycleStats:
    competitors_checked: int = 0
    reels_found: int = 0
    comment_requests: int = 0
    comments_seen: int = 0
    comments_created: int = 0
    leads_created: int = 0
    hot_notifications: int = 0
    errors: int = 0


@dataclass(frozen=True, slots=True)
class PostCheck:
    post_id: int
    should_fetch_comments: bool
    is_baseline: bool


class InstagramMonitor:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        provider: InstagramProvider,
        contact_service: ContactService,
        lead_service: LeadService,
        notifier: LeadNotifier,
        competitors: list[str],
        process_existing_comments: bool,
        force_refresh_seconds: int = 3600,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.contact_service = contact_service
        self.lead_service = lead_service
        self.notifier = notifier
        self.competitors = competitors
        self.process_existing_comments = process_existing_comments
        self.force_refresh_seconds = force_refresh_seconds

    async def run_cycle(self) -> CycleStats:
        stats = CycleStats()
        try:
            stats.hot_notifications += await self.notifier.flush_pending()
        except Exception as exc:
            stats.errors += 1
            logger.exception(
                "notification_outbox_flush_failed error_type=%s", type(exc).__name__
            )
        pending_leads = await self.lead_service.retry_pending()
        for lead in pending_leads:
            stats.leads_created += 1
            if lead.is_hot:
                try:
                    stats.hot_notifications += await self.notifier.notify_hot_lead(
                        lead.lead_id
                    )
                except Exception as exc:
                    stats.errors += 1
                    logger.exception(
                        "pending_lead_notification_failed lead_id=%s error_type=%s",
                        lead.lead_id,
                        type(exc).__name__,
                    )
        for handle in self.competitors:
            try:
                reels = await self.provider.get_reels(handle)
                competitor_failed = False
                stats.competitors_checked += 1
                stats.reels_found += len(reels)
                logger.info("competitor_checked competitor=%s reels=%s", handle, len(reels))
                for reel in reels:
                    try:
                        await self._process_reel(reel, stats)
                    except Exception as exc:
                        competitor_failed = True
                        stats.errors += 1
                        logger.exception(
                            "reel_processing_failed competitor=%s post_id=%s error_type=%s",
                            handle,
                            reel.platform_post_id,
                            type(exc).__name__,
                        )
                if not competitor_failed:
                    await self._complete_baseline(handle)
            except ProviderError as exc:
                stats.errors += 1
                logger.error(
                    "competitor_check_failed competitor=%s error_type=%s",
                    handle,
                    type(exc).__name__,
                )
        return stats

    async def _process_reel(self, reel: InstagramPost, stats: CycleStats) -> None:
        check = await self._prepare_post(reel)
        if not check.should_fetch_comments:
            return
        comments = await self.provider.get_comments(reel)
        stats.comment_requests += 1
        stats.comments_seen += len(comments)
        for comment in comments:
            signal = await self.contact_service.persist_signal(
                reel, comment, is_baseline=check.is_baseline
            )
            if not signal.created:
                continue
            stats.comments_created += 1
            lead = await self.lead_service.process_signal(signal)
            if lead is None or not lead.created:
                continue
            stats.leads_created += 1
            if lead.is_hot:
                try:
                    stats.hot_notifications += await self.notifier.notify_hot_lead(
                        lead.lead_id
                    )
                except Exception as exc:
                    stats.errors += 1
                    logger.exception(
                        "lead_notification_failed lead_id=%s error_type=%s",
                        lead.lead_id,
                        type(exc).__name__,
                    )
        await self._mark_comments_fetched(check.post_id, reel.comments_count)

    async def _prepare_post(self, reel: InstagramPost) -> PostCheck:
        async with self.session_factory() as session:
            competitor = await CompetitorRepository(session).get_or_create(reel.competitor)
            post, _, _ = await PostRepository(session).upsert(competitor, reel)
            provider_changed = competitor.baseline_provider != self.provider.name
            is_first_baseline = (
                (competitor.baseline_completed_at is None or provider_changed)
                and not self.process_existing_comments
            )
            refresh_before = datetime.now(UTC) - timedelta(
                seconds=self.force_refresh_seconds
            )
            comments_checked_at = post.comments_checked_at
            if comments_checked_at is not None and comments_checked_at.tzinfo is None:
                comments_checked_at = comments_checked_at.replace(tzinfo=UTC)
            refresh_due = (
                comments_checked_at is None
                or comments_checked_at <= refresh_before
            )
            should_fetch = (
                provider_changed
                or post.comments_fetched_count != reel.comments_count
                or refresh_due
            )
            await session.commit()
            return PostCheck(
                post_id=post.id,
                should_fetch_comments=should_fetch,
                is_baseline=is_first_baseline,
            )

    async def _mark_comments_fetched(self, post_id: int, comments_count: int) -> None:
        async with self.session_factory() as session:
            post = await session.get(Post, post_id)
            if post is None:
                raise RuntimeError(f"Post {post_id} disappeared during polling")
            post.comments_fetched_count = comments_count
            post.comments_checked_at = datetime.now(UTC)
            await session.commit()

    async def _complete_baseline(self, handle: str) -> None:
        async with self.session_factory() as session:
            competitor = await CompetitorRepository(session).get_or_create(handle)
            if (
                competitor.baseline_completed_at is None
                or competitor.baseline_provider != self.provider.name
            ):
                competitor.baseline_completed_at = datetime.now(UTC)
                competitor.baseline_provider = self.provider.name
                await session.commit()
