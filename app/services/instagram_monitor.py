from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Comment, Competitor, CoverageStatus, Post
from app.db.repositories import CompetitorRepository, PostRepository
from app.providers.base import InstagramProvider, ProviderError, ProviderUsageBlockedError
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
    change_notifications: int = 0
    historical_analyzed: int = 0
    errors: int = 0
    budget_stops: int = 0


@dataclass(frozen=True, slots=True)
class PostCheck:
    post_id: int
    should_fetch_comments: bool
    is_baseline: bool
    known_comment_ids: set[str]
    previous_coverage: CoverageStatus


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
        auto_repair_partial_coverage: bool = False,
        baseline_max_comment_pages: int = 1,
        incremental_max_comment_pages: int = 2,
        analyze_baseline_comments: bool = False,
        historical_analysis_batch_size: int = 0,
        retry_pending_enabled: bool = False,
        retry_pending_batch_size: int = 5,
        retry_pending_cooldown_seconds: int = 3600,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.contact_service = contact_service
        self.lead_service = lead_service
        self.notifier = notifier
        self.competitors = competitors
        self.process_existing_comments = process_existing_comments
        self.force_refresh_seconds = force_refresh_seconds
        self.auto_repair_partial_coverage = auto_repair_partial_coverage
        self.baseline_max_comment_pages = max(1, baseline_max_comment_pages)
        self.incremental_max_comment_pages = max(1, incremental_max_comment_pages)
        self.analyze_baseline_comments = analyze_baseline_comments
        self.historical_analysis_batch_size = historical_analysis_batch_size
        self.retry_pending_enabled = retry_pending_enabled
        self.retry_pending_batch_size = retry_pending_batch_size
        self.retry_pending_cooldown_seconds = retry_pending_cooldown_seconds

    async def run_cycle(self, *, force: bool = True) -> CycleStats:
        self.provider.begin_cycle()
        stats = CycleStats()
        try:
            stats.hot_notifications += await self.notifier.flush_pending()
        except Exception as exc:
            stats.errors += 1
            logger.exception(
                "notification_outbox_flush_failed error_type=%s", type(exc).__name__
            )
        pending_leads = (
            await self.lead_service.retry_pending(
                self.retry_pending_batch_size,
                cooldown_seconds=self.retry_pending_cooldown_seconds,
            )
            if self.retry_pending_enabled
            else []
        )
        for lead in pending_leads:
            stats.leads_created += 1
            try:
                stats.hot_notifications += await self._notify_analyzed(lead.lead_id, lead.is_hot)
                if lead.significant_change_id is not None:
                    stats.change_notifications += await self._notify_significant_change(
                        lead.significant_change_id
                    )
            except Exception as exc:
                stats.errors += 1
                logger.exception(
                    "pending_lead_notification_failed lead_id=%s error_type=%s",
                    lead.lead_id,
                    type(exc).__name__,
                )
        if self.analyze_baseline_comments and self.historical_analysis_batch_size > 0:
            try:
                historical = await self.lead_service.backfill_unanalyzed_comments(
                    self.historical_analysis_batch_size
                )
                stats.historical_analyzed += len(historical)
            except Exception as exc:
                stats.errors += 1
                logger.exception(
                    "historical_analysis_failed error_type=%s", type(exc).__name__
                )

        handles = await self._active_competitors(force=force)
        for handle in handles:
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
                    await self._mark_competitor_scan(handle, success=True)
            except ProviderUsageBlockedError as exc:
                # A safety/budget guard is global for this cycle. Continuing with more competitors
                # would only produce repeated blocked attempts, so stop cleanly.
                stats.budget_stops += 1
                logger.warning(
                    "monitor_cycle_budget_stopped competitor=%s error=%s",
                    handle,
                    str(exc)[:200],
                )
                break
            except ProviderError as exc:
                stats.errors += 1
                await self._mark_competitor_scan(handle, success=False)
                logger.error(
                    "competitor_check_failed competitor=%s error_type=%s",
                    handle,
                    type(exc).__name__,
                )
        return stats

    async def _active_competitors(self, *, force: bool) -> list[str]:
        """Load competitors from DB so UI changes take effect without restarting the bot."""
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            repo = CompetitorRepository(session)
            for configured in self.competitors:
                await repo.get_or_create(configured)
            await session.commit()
            rows = (await session.scalars(select(Competitor))).all()
        result: list[str] = []
        for competitor in rows:
            if not competitor.active:
                continue
            if force or competitor.last_scanned_at is None:
                result.append(competitor.normalized_handle)
                continue
            last = competitor.last_scanned_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if last + timedelta(seconds=max(30, competitor.poll_interval_seconds)) <= now:
                result.append(competitor.normalized_handle)
        return result

    async def _mark_competitor_scan(self, handle: str, *, success: bool) -> None:
        async with self.session_factory() as session:
            competitor = await CompetitorRepository(session).get_or_create(handle)
            competitor.last_scanned_at = datetime.now(UTC)
            if success:
                competitor.scan_error_count = 0
            else:
                competitor.scan_error_count += 1
            await session.commit()

    async def _process_reel(self, reel: InstagramPost, stats: CycleStats) -> None:
        check = await self._prepare_post(reel)
        if not check.should_fetch_comments:
            return
        batch = await self.provider.get_comment_batch(
            reel,
            known_comment_ids=check.known_comment_ids,
            max_pages=(
                self.baseline_max_comment_pages
                if check.is_baseline
                else self.incremental_max_comment_pages
            ),
        )
        comments = batch.comments
        stats.comment_requests += batch.pages_fetched
        stats.comments_seen += len(comments)
        for comment in comments:
            signal = await self.contact_service.persist_signal(
                reel, comment, is_baseline=check.is_baseline
            )
            if not signal.created:
                continue
            stats.comments_created += 1
            if signal.is_baseline:
                continue
            lead = await self.lead_service.ensure_analyzing(signal)
            if not lead.created:
                continue
            stats.leads_created += 1
            notified_initially = False
            try:
                sent = await self._notify_new_signal(lead.lead_id)
                notified_initially = sent > 0
                stats.hot_notifications += sent
            except Exception as exc:
                stats.errors += 1
                logger.exception(
                    "signal_notification_failed lead_id=%s error_type=%s",
                    lead.lead_id,
                    type(exc).__name__,
                )
            analyzed = await self.lead_service.analyze_lead(lead.lead_id)
            try:
                stats.hot_notifications += await self._notify_analyzed(
                    analyzed.lead_id,
                    analyzed.is_hot,
                    initial_already_sent=notified_initially,
                )
                if analyzed.significant_change_id is not None:
                    stats.change_notifications += await self._notify_significant_change(
                        analyzed.significant_change_id
                    )
            except Exception as exc:
                stats.errors += 1
                logger.exception(
                    "lead_enrichment_notification_failed lead_id=%s error_type=%s",
                    analyzed.lead_id,
                    type(exc).__name__,
                )
        await self._mark_comments_fetched(
            check.post_id,
            remote_comments_count=reel.comments_count,
            fetched_count=len(comments),
            pages_fetched=batch.pages_fetched,
            coverage_status=batch.coverage_status,
            provider=batch.provider,
            previous_coverage=check.previous_coverage,
            stopped_on_known_comment=batch.stopped_on_known_comment,
        )

    async def _notify_new_signal(self, lead_id: int) -> int:
        notify = getattr(self.notifier, "notify_new_signal", None)
        if notify is not None:
            return await notify(lead_id)
        # Compatibility for custom integrations while they adopt the V4 protocol.
        return await self.notifier.notify_hot_lead(lead_id)

    async def _notify_analyzed(
        self, lead_id: int, is_hot: bool, *, initial_already_sent: bool = False
    ) -> int:
        notify = getattr(self.notifier, "notify_analyzed_lead", None)
        if notify is not None:
            return await notify(lead_id)
        if is_hot and not initial_already_sent:
            return await self.notifier.notify_hot_lead(lead_id)
        return 0

    async def _notify_significant_change(self, change_id: int) -> int:
        notify = getattr(self.notifier, "notify_significant_change", None)
        if notify is None:
            return 0
        return await notify(change_id)

    async def _prepare_post(self, reel: InstagramPost) -> PostCheck:
        async with self.session_factory() as session:
            competitor = await CompetitorRepository(session).get_or_create(reel.competitor)
            post, _, _ = await PostRepository(session).upsert(competitor, reel)
            provider_changed = competitor.baseline_provider != self.provider.name
            is_first_baseline = (
                (competitor.baseline_completed_at is None or provider_changed)
                and not self.process_existing_comments
            )
            now = datetime.now(UTC)
            refresh_before = (
                now - timedelta(seconds=self.force_refresh_seconds)
                if self.force_refresh_seconds > 0
                else None
            )
            comments_checked_at = post.comments_checked_at
            if comments_checked_at is not None and comments_checked_at.tzinfo is None:
                comments_checked_at = comments_checked_at.replace(tzinfo=UTC)
            refresh_due = bool(
                self.auto_repair_partial_coverage
                and post.coverage_status != CoverageStatus.FULL
                and refresh_before is not None
                and comments_checked_at is not None
                and comments_checked_at <= refresh_before
            )

            # Zero comments are authoritative from the Reel metadata and do not justify a second
            # paid Comments API call. Mark the post synchronized locally.
            if reel.comments_count == 0:
                post.comments_fetched_count = 0
                post.last_synced_remote_count = 0
                post.comment_pages_fetched = 0
                post.coverage_status = CoverageStatus.FULL
                post.last_comment_provider = "metadata"
                post.comments_checked_at = now
                await session.commit()
                return PostCheck(
                    post_id=post.id,
                    should_fetch_comments=False,
                    is_baseline=is_first_baseline,
                    known_comment_ids=set(),
                    previous_coverage=CoverageStatus.FULL,
                )

            should_fetch = (
                provider_changed
                or comments_checked_at is None
                or post.last_synced_remote_count != reel.comments_count
                or refresh_due
            )

            known_ids = set(
                (
                    await session.scalars(
                        select(Comment.platform_comment_id)
                        .where(Comment.post_id == post.id)
                        .order_by(desc(Comment.discovered_at), desc(Comment.id))
                        .limit(250)
                    )
                ).all()
            )
            await session.commit()
            return PostCheck(
                post_id=post.id,
                should_fetch_comments=should_fetch,
                is_baseline=is_first_baseline,
                known_comment_ids=known_ids,
                previous_coverage=post.coverage_status,
            )

    async def _mark_comments_fetched(
        self,
        post_id: int,
        *,
        remote_comments_count: int,
        fetched_count: int,
        pages_fetched: int,
        coverage_status: str,
        provider: str,
        previous_coverage: CoverageStatus,
        stopped_on_known_comment: bool,
    ) -> None:
        async with self.session_factory() as session:
            post = await session.get(Post, post_id)
            if post is None:
                raise RuntimeError(f"Post {post_id} disappeared during polling")
            stored_count = int(
                await session.scalar(
                    select(func.count(Comment.id)).where(Comment.post_id == post_id)
                )
                or 0
            )
            # This field now means "how many unique comments we have stored for this Reel", not
            # merely how many happened to be present on the last API page. That makes coverage
            # truthful during cheap incremental refreshes.
            post.comments_fetched_count = stored_count
            post.last_synced_remote_count = remote_comments_count
            post.comment_pages_fetched = pages_fetched
            try:
                resolved_coverage = CoverageStatus(coverage_status)
            except ValueError:
                resolved_coverage = CoverageStatus.UNKNOWN
            if stored_count >= remote_comments_count:
                resolved_coverage = CoverageStatus.FULL
            elif stopped_on_known_comment:
                # Incremental sync completed as soon as a known comment was encountered. Preserve
                # what we knew about historical coverage instead of falsely downgrading a FULL Reel.
                resolved_coverage = (
                    previous_coverage
                    if previous_coverage != CoverageStatus.UNKNOWN
                    else CoverageStatus.PARTIAL
                )
            elif resolved_coverage == CoverageStatus.FULL and remote_comments_count > stored_count:
                resolved_coverage = CoverageStatus.PARTIAL
            post.coverage_status = resolved_coverage
            post.last_comment_provider = provider
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
