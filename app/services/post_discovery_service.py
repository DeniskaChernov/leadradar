from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CoverageStatus, PostDiscoveryState
from app.schemas.instagram import PostFetchResult


class PostDiscoveryService:
    """Update traversal in the same transaction that saves its publications."""

    MAX_VISITED_CURSORS = 512
    BLOCKED_REASONS = frozenset({"RepeatedPostCursor", "PostCursorHistoryLimit"})

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_page(
        self, competitor_id: int, page: PostFetchResult, *, requested_cursor: str | None,
        refresh_seconds: int = 21600,
    ) -> PostDiscoveryState:
        state = await self.session.scalar(select(PostDiscoveryState).where(
            PostDiscoveryState.competitor_id == competitor_id,
            PostDiscoveryState.provider == page.provider,
        ))
        if state is None:
            state = PostDiscoveryState(competitor_id=competitor_id, provider=page.provider)
            self.session.add(state)
            await self.session.flush()
        now = datetime.now(UTC)
        if requested_cursor is None:
            state.head_checked_at = now
        # A refreshed head must not erase a durable historical continuation.
        if requested_cursor is None and state.page_checked_at is not None:
            completed = state.completed_at
            if completed is not None and completed.tzinfo is None:
                completed = completed.replace(tzinfo=UTC)
            restart_due = completed is not None and completed <= now - timedelta(
                seconds=max(1, refresh_seconds)
            )
            if not restart_due:
                if page.fetch_error:
                    state.stop_reason = page.fetch_error
                return state
            if page.fetch_error:
                state.stop_reason = page.fetch_error
                return state
            state.visited_cursors = []
        # Delayed/replayed pages cannot overwrite a newer committed position.
        if requested_cursor is not None and state.next_cursor != requested_cursor:
            return state
        if page.fetch_error:
            state.coverage_status = CoverageStatus.PARTIAL
            state.stop_reason = page.fetch_error
            # Keep the failed request cursor (None means retry the head).
            state.next_cursor = requested_cursor
            state.completed_at = None
            return state
        if page.coverage_status == "UNKNOWN":
            state.coverage_status = CoverageStatus.UNKNOWN
            state.stop_reason = "PaginationUnknown"
            return state
        visited = list(state.visited_cursors or [])
        if requested_cursor is not None and requested_cursor not in visited:
            visited.append(requested_cursor)
        if page.next_cursor is not None and page.next_cursor in visited:
            state.coverage_status = CoverageStatus.PARTIAL
            state.stop_reason = "RepeatedPostCursor"
            state.visited_cursors = visited
            return state
        if len(visited) >= self.MAX_VISITED_CURSORS and page.next_cursor is not None:
            state.coverage_status = CoverageStatus.PARTIAL
            state.stop_reason = "PostCursorHistoryLimit"
            state.visited_cursors = visited
            return state
        state.visited_cursors = visited
        state.page_checked_at = now
        state.next_cursor = page.next_cursor
        state.coverage_status = (
            CoverageStatus.FULL if page.cursor_exhausted else CoverageStatus.PARTIAL
        )
        state.completed_at = now if page.cursor_exhausted else None
        state.stop_reason = "Exhausted" if page.cursor_exhausted else "SavedContinuation"
        return state
