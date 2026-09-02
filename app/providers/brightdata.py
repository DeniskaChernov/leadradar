from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from app.providers.base import (
    HTTPInstagramProvider,
    ProviderAuthError,
    ProviderResponseError,
    parse_datetime,
)
from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
)


class BrightDataProvider(HTTPInstagramProvider):
    name = "brightdata"

    def __init__(
        self,
        api_key: str,
        *,
        api_url: str,
        profile_dataset_id: str,
        posts_dataset_id: str,
        reels_dataset_id: str,
        comments_dataset_id: str,
        timeout_seconds: float = 25,
        max_attempts: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds, max_attempts=max_attempts, client=client
        )
        self.api_key = api_key
        self.api_url = api_url
        self.profile_dataset_id = profile_dataset_id
        self.posts_dataset_id = posts_dataset_id
        self.reels_dataset_id = reels_dataset_id
        self.comments_dataset_id = comments_dataset_id

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderAuthError("BRIGHTDATA_API_KEY is not configured")
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def _scrape(
        self,
        dataset_id: str,
        inputs: list[dict[str, Any]],
        *,
        discover: bool = False,
        discover_by: str = "url",
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"dataset_id": dataset_id, "format": "json"}
        if discover:
            params.update({"type": "discover_new", "discover_by": discover_by})
        payload = await self._request_json(
            "POST", self.api_url, headers=self.headers, params=params, json=inputs
        )
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            payload = payload["data"]
        if not isinstance(payload, list):
            raise ProviderResponseError("Bright Data response is not a JSON list")
        return [item for item in payload if isinstance(item, dict) and not item.get("error")]

    async def get_profile(self, handle: str) -> InstagramProfile:
        url = f"https://www.instagram.com/{handle.strip().lstrip('@')}/"
        rows = await self._scrape(self.profile_dataset_id, [{"url": url}])
        if not rows:
            raise ProviderResponseError("Bright Data profile response is empty")
        row = rows[0]
        username = _first_string(row, "account", "user_name", "username")
        return InstagramProfile(
            platform_user_id=_optional_string(row.get("id")),
            username=username,
            display_name=_optional_string(row.get("full_name")),
            profile_url=url,
            raw_data=row,
        )

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        normalized = handle.strip().lower().lstrip("@")
        url = f"https://www.instagram.com/{normalized}/"
        rows = await self._scrape(
            self.reels_dataset_id,
            [{"url": url, "num_of_posts": 12}],
            discover=True,
            discover_by="url",
        )
        return [self.normalize_post(row, normalized) for row in rows]

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        dataset_id = self.reels_dataset_id if "/reel/" in url else self.posts_dataset_id
        rows = await self._scrape(dataset_id, [{"url": url}])
        if not rows:
            raise ProviderResponseError("Bright Data post response is empty")
        return self.normalize_post(rows[0], competitor)

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        return (await self.get_comment_batch(post)).comments

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
    ) -> CommentFetchResult:
        rows = await self._scrape(self.comments_dataset_id, [{"url": post.url}])
        comments = [self.normalize_comment(row) for row in rows]
        coverage = "FULL" if post.comments_count <= len(comments) else "LATEST_ONLY"
        return CommentFetchResult(
            comments=comments,
            provider=self.name,
            pages_fetched=1,
            coverage_status=coverage,
            cursor_exhausted=coverage == "FULL",
        )

    @staticmethod
    def normalize_post(row: dict[str, Any], competitor: str) -> InstagramPost:
        url = _first_string(row, "url")
        shortcode = _optional_string(row.get("shortcode")) or _shortcode_from_url(url)
        post_id = _optional_string(row.get("post_id") or row.get("id")) or shortcode
        if not post_id:
            raise ProviderResponseError("Bright Data post has no id, post_id, or shortcode")
        return InstagramPost(
            platform_post_id=post_id,
            competitor=competitor,
            url=url,
            caption=str(row.get("description") or row.get("caption") or ""),
            post_type="REEL" if "/reel/" in url else "POST",
            published_at=parse_datetime(row.get("date_posted") or row.get("datetime")),
            comments_count=int(row.get("num_comments") or row.get("comments") or 0),
            raw_data=row,
        )

    @staticmethod
    def normalize_comment(row: dict[str, Any]) -> InstagramComment:
        username = _first_string(row, "comment_user")
        profile_url = _optional_string(row.get("comment_user_url")) or (
            f"https://www.instagram.com/{username}/"
        )
        parent_id = _optional_string(
            row.get("parent_comment_id")
            or row.get("reply_to_comment_id")
            or row.get("parent_id")
        )
        return InstagramComment(
            platform_comment_id=_first_string(row, "comment_id"),
            platform_user_id=_optional_string(row.get("comment_user_id")),
            username=username,
            display_name=None,
            profile_url=profile_url,
            text=_first_string(row, "comment", allow_empty=True),
            created_at=parse_datetime(row.get("comment_date")),
            parent_platform_comment_id=parent_id,
            raw_data=row,
        )


def _first_string(row: dict[str, Any], *keys: str, allow_empty: bool = False) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and (allow_empty or value != ""):
            return str(value)
    raise ProviderResponseError(f"Bright Data response missing one of: {', '.join(keys)}")


def _optional_string(value: object) -> str | None:
    return None if value in (None, "") else str(value)


def _shortcode_from_url(url: str) -> str | None:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"p", "reel"}:
        return parts[1]
    return None

