"""Read-only presentation of saved public signals, grouped by their real source."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.db.models import Competitor, CoverageStatus, Post


@dataclass(slots=True)
class RadarPostGroup:
    post: Post
    total: int
    leads: int
    hot: int
    pending: int
    rejected: int
    rows: list = field(default_factory=list)
    comments_url: str = ""

    @property
    def public_url(self) -> str | None:
        try:
            parsed = urlsplit(self.post.url)
            if (
                parsed.scheme in {"http", "https"}
                and parsed.hostname in {"instagram.com", "www.instagram.com", "m.instagram.com"}
                and not parsed.username
                and not parsed.password
            ):
                return self.post.url
        except ValueError:
            pass
        return None

    @property
    def coverage(self) -> str:
        # FULL describes the saved snapshot, never a promise about current Instagram.
        post = self.post
        if post.comments_checked_at is None:
            return CoverageStatus.UNKNOWN.value
        if post.comment_backfill_cursor or (
            post.last_synced_remote_count is not None
            and post.last_synced_remote_count != post.comments_count
        ):
            return CoverageStatus.PARTIAL.value
        return post.coverage_status.value


@dataclass(slots=True)
class RadarCompanyGroup:
    competitor: Competitor
    post_count: int
    total: int
    leads: int
    hot: int
    pending: int
    rejected: int
    posts: list[RadarPostGroup] = field(default_factory=list)
    source_url: str = ""


@dataclass(slots=True)
class RadarResultsPage:
    pagination: object
    companies: list[RadarCompanyGroup]
    rows: list
    post_count: int
    company_count: int
    comment_count: int

