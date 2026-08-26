from __future__ import annotations

from typing import Any

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


class ScrapeCreatorsProvider(HTTPInstagramProvider):
    name = "scrapecreators"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.scrapecreators.com",
        timeout_seconds: float = 25,
        max_attempts: int = 3,
        max_comment_pages: int = 10,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds, max_attempts=max_attempts, client=client
        )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_comment_pages = max(1, max_comment_pages)

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderAuthError("SCRAPECREATORS_API_KEY is not configured")
        return {"x-api-key": self.api_key}

    async def get_profile(self, handle: str) -> InstagramProfile:
        payload = await self._request_json(
            "GET",
            f"{self.base_url}/v1/instagram/profile",
            headers=self.headers,
            params={"handle": handle, "trim": "true"},
        )
        user = payload.get("data", {}).get("user") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            raise ProviderResponseError("ScrapeCreators profile response has no data.user")
        username = _required_string(user, "username")
        return InstagramProfile(
            platform_user_id=_optional_string(user.get("id")),
            username=username,
            display_name=_optional_string(user.get("full_name")),
            profile_url=f"https://www.instagram.com/{username}/",
            raw_data=payload,
        )

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        payload = await self._request_json(
            "GET",
            f"{self.base_url}/v2/instagram/user/posts",
            headers=self.headers,
            params={"handle": handle, "trim": "false"},
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderResponseError("ScrapeCreators posts response has no items list")
        reels = []
        for item in items:
            if isinstance(item, dict) and item.get("product_type") == "clips":
                reels.append(self.normalize_post(item, handle))
        return reels

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        payload = await self._request_json(
            "GET",
            f"{self.base_url}/v1/instagram/post",
            headers=self.headers,
            params={"url": url},
        )
        item = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(item, dict) and isinstance(item.get("xdt_shortcode_media"), dict):
            item = item["xdt_shortcode_media"]
        if not isinstance(item, dict):
            raise ProviderResponseError("ScrapeCreators post response has no documented post data")
        return self.normalize_post(item, competitor)

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        return (await self.get_comment_batch(post)).comments

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
    ) -> CommentFetchResult:
        comments: list[InstagramComment] = []
        seen_ids: set[str] = set()
        known_comment_ids = known_comment_ids or set()
        cursor: str | None = None
        pages = 0
        cursor_exhausted = False
        stopped_on_known = False
        page_limit = self.max_comment_pages
        if max_pages is not None:
            page_limit = max(1, min(page_limit, int(max_pages)))

        while pages < page_limit:
            params = {"url": post.url, "include_replies": "false"}
            if cursor:
                params["cursor"] = cursor
            payload = await self._request_json(
                "GET",
                f"{self.base_url}/v2/instagram/post/comments",
                headers=self.headers,
                params=params,
            )
            items = payload.get("comments") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise ProviderResponseError("ScrapeCreators comments response has no comments list")
            pages += 1
            page_has_known = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                normalized = self.normalize_comment(item)
                if normalized.platform_comment_id in known_comment_ids:
                    page_has_known = True
                if normalized.platform_comment_id in seen_ids:
                    continue
                seen_ids.add(normalized.platform_comment_id)
                comments.append(normalized)

            # Instagram comment pages are returned newest-first. Once we hit a comment already
            # stored in our DB, all new comments needed for the incremental sync are on the pages
            # we already fetched. Stopping here usually turns a 10-page refresh into one request.
            if page_has_known:
                stopped_on_known = True
                break

            next_cursor = payload.get("cursor") if isinstance(payload, dict) else None
            if not next_cursor:
                cursor_exhausted = True
                break
            if str(next_cursor) == cursor:
                break
            cursor = str(next_cursor)

        coverage = "FULL" if cursor_exhausted else "UNKNOWN" if stopped_on_known else "PARTIAL"
        return CommentFetchResult(
            comments=comments,
            provider=self.name,
            pages_fetched=pages,
            coverage_status=coverage,
            cursor_exhausted=cursor_exhausted,
            stopped_on_known_comment=stopped_on_known,
        )

    @staticmethod
    def normalize_post(item: dict[str, Any], competitor: str) -> InstagramPost:
        post_id = _required_string(item, "id")
        shortcode = _optional_string(item.get("code")) or _optional_string(item.get("shortcode"))
        if not shortcode:
            raise ProviderResponseError("ScrapeCreators post has no code/shortcode")
        caption_value = item.get("caption")
        caption = caption_value.get("text", "") if isinstance(caption_value, dict) else ""
        return InstagramPost(
            platform_post_id=post_id,
            competitor=competitor,
            url=f"https://www.instagram.com/reel/{shortcode}/",
            caption=str(caption),
            post_type="REEL" if item.get("product_type") == "clips" else "POST",
            published_at=parse_datetime(item.get("created_at") or item.get("taken_at")),
            comments_count=int(item.get("comment_count") or 0),
            raw_data=item,
        )

    @staticmethod
    def normalize_comment(item: dict[str, Any]) -> InstagramComment:
        user = item.get("user")
        if not isinstance(user, dict):
            raise ProviderResponseError("ScrapeCreators comment has no user")
        username = _required_string(user, "username")
        return InstagramComment(
            platform_comment_id=_required_string(item, "id"),
            platform_user_id=_optional_string(user.get("id") or user.get("pk")),
            username=username,
            display_name=_optional_string(user.get("full_name")),
            profile_url=f"https://www.instagram.com/{username}/",
            text=_required_string(item, "text", allow_empty=True),
            created_at=parse_datetime(item.get("created_at")),
            raw_data=item,
        )


def _required_string(item: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = item.get(key)
    if value is None or (not allow_empty and value == ""):
        raise ProviderResponseError(f"ScrapeCreators response field {key!r} is missing")
    return str(value)


def _optional_string(value: object) -> str | None:
    return None if value in (None, "") else str(value)

