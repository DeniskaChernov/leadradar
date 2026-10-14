from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from app.providers.base import (
    HTTPInstagramProvider,
    ProviderAuthError,
    ProviderError,
    ProviderResponseError,
    ProviderUsageBlockedError,
    parse_datetime,
)
from app.providers.public_data import ensure_public_source, public_record
from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
    PostFetchResult,
    ProviderCreditObservation,
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
        self._credit_observations: list[ProviderCreditObservation] = []

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderAuthError("SCRAPECREATORS_API_KEY is not configured")
        return {"x-api-key": self.api_key}

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        # One delivered request per durable reservation. A lost/failed response
        # is reconciled by the budget wrapper, never retried inside the adapter.
        kwargs["attempts"] = 1
        payload = await super()._request_json(method, url, **kwargs)
        self._capture_credit_observation(payload, url)
        return payload

    def pop_credit_observations(self) -> list[ProviderCreditObservation]:
        observations = self._credit_observations
        self._credit_observations = []
        return observations

    def _capture_credit_observation(self, payload: Any, url: str) -> None:
        if not isinstance(payload, dict):
            return
        containers = [
            payload,
            payload.get("meta"),
            payload.get("data"),
        ]
        remaining = None
        charged = None
        for container in containers:
            if not isinstance(container, dict):
                continue
            if remaining is None:
                remaining = _optional_nonnegative_int(container.get("credits_remaining"))
            if charged is None:
                charged = _optional_nonnegative_int(container.get("credits_charged"))
        if remaining is None and charged is None:
            return
        operation = (
            "get_reply_page"
            if url.endswith("/v1/instagram/post/comment/replies")
            else
            "get_comment_page"
            if url.endswith("/v2/instagram/post/comments")
            else "get_reels"
            if url.endswith("/v2/instagram/user/posts")
            else "get_profile"
            if url.endswith("/v1/instagram/profile")
            else "get_post"
        )
        self._credit_observations.append(
            ProviderCreditObservation(
                idempotency_key=f"scrapecreators-response:{uuid4().hex}",
                provider=self.name,
                operation=operation,
                credits_remaining=remaining,
                credits_charged=charged,
            )
        )

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
        ensure_public_source(payload)
        username = _required_string(user, "username")
        return public_record(InstagramProfile(
            platform_user_id=_optional_string(user.get("id")),
            username=username,
            display_name=_optional_string(user.get("full_name")),
            profile_url=f"https://www.instagram.com/{username}/",
        ))

    @property
    def supports_post_pagination(self) -> bool:
        return True

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        return (await self.get_post_page(handle)).posts

    async def get_post_page(self, handle: str, *, cursor: str | None = None) -> PostFetchResult:
        if cursor is not None and (not cursor or len(cursor) > 4096):
            raise ProviderResponseError("Invalid publication request cursor")
        params = {"handle": handle, "trim": "false"}
        if cursor is not None:
            params["next_max_id"] = cursor
        payload = await self._request_json(
            "GET",
            f"{self.base_url}/v2/instagram/user/posts",
            headers=self.headers,
            params=params,
            # One reserved credit authorizes one HTTP attempt. An ambiguous
            # failure must return to the budget guard before another paid call.
            attempts=1,
        )
        ensure_public_source(payload)
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ProviderResponseError("ScrapeCreators posts response has no items list")
        posts = []
        seen_ids: set[str] = set()
        fetch_error = None
        for item in items:
            try:
                if not isinstance(item, dict):
                    raise ProviderResponseError("Invalid publication record")
                post = self.normalize_post(item, handle)
                if post.platform_post_id not in seen_ids:
                    posts.append(post)
                    seen_ids.add(post.platform_post_id)
            except ProviderUsageBlockedError:
                raise
            except (ProviderResponseError, ValueError, TypeError, OverflowError):
                fetch_error = "MalformedPost"
        next_cursor = payload.get("next_max_id")
        more = payload.get("more_available")
        if next_cursor in (None, ""):
            next_cursor = None
        elif not isinstance(next_cursor, str) or len(next_cursor) > 4096:
            fetch_error = "InvalidPostCursor"
            next_cursor = None
        if more is not None and not isinstance(more, bool):
            fetch_error = "InvalidPostPagination"
        elif more is True and next_cursor is None:
            fetch_error = "MissingPostCursor"
        elif more is False and next_cursor is not None:
            fetch_error = "ConflictingPostPagination"
        if next_cursor is not None and next_cursor == cursor:
            fetch_error = "RepeatedPostCursor"
        if fetch_error:
            # Valid siblings can be committed, but retry the requested page;
            # never skip an invalid record by advancing its publication cursor.
            return PostFetchResult(
                posts=posts, provider=self.name, coverage_status="PARTIAL",
                next_cursor=cursor, fetch_error=fetch_error,
            )
        exhausted = more is False
        # This same public response includes photos and carousels. Retain the
        # adapter method name for compatibility without discarding these posts.
        return PostFetchResult(
            posts=posts, provider=self.name,
            coverage_status="FULL" if exhausted else "PARTIAL" if next_cursor else "UNKNOWN",
            cursor_exhausted=exhausted, next_cursor=next_cursor,
        )

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        payload = await self._request_json(
            "GET",
            f"{self.base_url}/v1/instagram/post",
            headers=self.headers,
            params={"url": url},
        )
        ensure_public_source(payload)
        item = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(item, dict) and isinstance(item.get("xdt_shortcode_media"), dict):
            item = item["xdt_shortcode_media"]
        if not isinstance(item, dict):
            raise ProviderResponseError("ScrapeCreators post response has no documented post data")
        return self.normalize_post(item, competitor)

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        return (await self.get_comment_batch(post)).comments

    @property
    def supports_comment_replies(self) -> bool:
        return True

    async def get_reply_batch(
        self, post: InstagramPost, parent_comment_id: str, *, cursor: str | None = None,
    ) -> CommentFetchResult:
        ensure_public_source(post.raw_data)
        if not parent_comment_id:
            raise ProviderResponseError("Parent comment ID is required")
        params = {"url": post.url, "comment_id": parent_comment_id}
        if cursor:
            params["cursor"] = cursor
        payload = await self._request_json(
            "GET", f"{self.base_url}/v1/instagram/post/comment/replies",
            headers=self.headers, params=params,
        )
        ensure_public_source(payload)
        if not isinstance(payload, dict) or not isinstance(payload.get("comments"), list):
            raise ProviderResponseError("ScrapeCreators replies response has no comments list")
        comments = []
        seen = set()
        error = None
        for item in payload["comments"]:
            try:
                if not isinstance(item, dict):
                    raise ProviderResponseError("Reply is not an object")
                reply = self.normalize_comment(item)
                if reply.platform_comment_id == parent_comment_id or (
                    reply.parent_platform_comment_id not in {None, parent_comment_id}
                ):
                    raise ProviderResponseError("Reply belongs to another thread")
                reply = public_record(reply.model_copy(update={
                    "parent_platform_comment_id": parent_comment_id,
                }))
            except ProviderUsageBlockedError:
                raise
            except (ProviderError, ValueError, TypeError, OverflowError):
                error = "InvalidReplyRecord"
                continue
            if reply.platform_comment_id not in seen:
                seen.add(reply.platform_comment_id)
                comments.append(reply)
        next_cursor = payload.get("cursor")
        more = payload.get("has_more")
        if next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor):
            error = "InvalidReplyCursor"
        if more is not None and not isinstance(more, bool):
            error = "InvalidReplyPagination"
        if (more is True and not next_cursor) or (more is False and next_cursor):
            error = "InconsistentReplyPagination"
        if next_cursor and next_cursor == cursor:
            error = "RepeatedReplyCursor"
        # Absence of cursor without explicit has_more=false cannot prove completion.
        exhausted = more is False and not error
        return CommentFetchResult(
            comments=comments, provider=self.name, pages_fetched=1,
            coverage_status="FULL" if exhausted else "PARTIAL" if error or next_cursor else "UNKNOWN",
            cursor_exhausted=exhausted,
            next_cursor=cursor if error else next_cursor, fetch_error=error,
        )

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
        cursor: str | None = None,
    ) -> CommentFetchResult:
        ensure_public_source(post.raw_data)
        comments: list[InstagramComment] = []
        seen_ids: set[str] = set()
        page_cursor: str | None = cursor
        requested_cursors: set[str | None] = set()
        pages = 0
        cursor_exhausted = False
        fetch_error: str | None = None
        page_limit = self.max_comment_pages
        if max_pages is not None:
            page_limit = max(1, min(page_limit, int(max_pages)))

        while pages < page_limit:
            requested_cursors.add(page_cursor)
            # Reply expansion costs 15 credits and is not consumed by this adapter.
            # Fetch parent comments at the regular page price; preserve reply IDs when present.
            params = {"url": post.url, "include_replies": "false"}
            if page_cursor:
                params["cursor"] = page_cursor
            try:
                payload = await self._request_json(
                    "GET",
                    f"{self.base_url}/v2/instagram/post/comments",
                    headers=self.headers,
                    params=params,
                )
                ensure_public_source(payload)
                items = payload.get("comments") if isinstance(payload, dict) else None
                if not isinstance(items, list):
                    raise ProviderResponseError(
                        "ScrapeCreators comments response has no comments list"
                    )
            except ProviderUsageBlockedError:
                raise
            except ProviderError as exc:
                if pages == 0:
                    raise
                fetch_error = type(exc).__name__
                break
            pages += 1
            record_error: ProviderError | None = None
            for item in items:
                try:
                    if not isinstance(item, dict):
                        raise ProviderResponseError("ScrapeCreators comment is not an object")
                    normalized = self.normalize_comment(item)
                except ProviderUsageBlockedError:
                    # Restricted data must remain a hard stop, never a partial
                    # public result or an excuse to try another provider.
                    raise
                except (ProviderError, ValueError, TypeError, OverflowError) as exc:
                    record_error = (
                        exc if isinstance(exc, ProviderError)
                        else ProviderResponseError("ScrapeCreators comment is invalid")
                    )
                    continue
                if normalized.platform_comment_id in seen_ids:
                    continue
                seen_ids.add(normalized.platform_comment_id)
                comments.append(normalized)
            if record_error is not None:
                if not comments:
                    raise record_error
                # Keep valid records on either side of the malformed item.
                # Leave the request cursor unchanged so a later manual scan
                # can retry this page without claiming complete coverage.
                fetch_error = type(record_error).__name__
                break

            # The public API does not guarantee chronological comment pages.
            # A known ID cannot prove that later pages have no new comments.
            # Respect the page limit and preserve the resumable cursor instead.

            next_cursor = payload.get("cursor") if isinstance(payload, dict) else None
            if not next_cursor:
                cursor_exhausted = True
                page_cursor = None
                break
            if str(next_cursor) in requested_cursors:
                # Keep the page that failed to advance resumable and visible as
                # an error, instead of erasing progress or repeatedly spending.
                fetch_error = "RepeatedCommentCursor"
                break
            page_cursor = str(next_cursor)

        coverage = "FULL" if cursor_exhausted else "PARTIAL"
        return CommentFetchResult(
            comments=comments,
            provider=self.name,
            pages_fetched=pages,
            coverage_status=coverage,
            cursor_exhausted=cursor_exhausted,
            stopped_on_known_comment=False,
            next_cursor=None if cursor_exhausted else page_cursor,
            fetch_error=fetch_error,
        )

    @staticmethod
    def normalize_post(item: dict[str, Any], competitor: str) -> InstagramPost:
        ensure_public_source(item)
        post_id = _required_string(item, "id")
        shortcode = _optional_string(item.get("code")) or _optional_string(item.get("shortcode"))
        if not shortcode:
            raise ProviderResponseError("ScrapeCreators post has no code/shortcode")
        caption_value = item.get("caption")
        caption = caption_value.get("text", "") if isinstance(caption_value, dict) else ""
        is_reel = item.get("product_type") == "clips"
        return public_record(InstagramPost(
            platform_post_id=post_id,
            competitor=competitor,
            url=f"https://www.instagram.com/{'reel' if is_reel else 'p'}/{shortcode}/",
            caption=str(caption),
            post_type="REEL" if is_reel else "POST",
            published_at=parse_datetime(item.get("created_at") or item.get("taken_at")),
            comments_count=int(item.get("comment_count") or 0),
        ))

    @staticmethod
    def normalize_comment(item: dict[str, Any]) -> InstagramComment:
        ensure_public_source(item, check_owner=False)
        user = item.get("user")
        if not isinstance(user, dict):
            raise ProviderResponseError("ScrapeCreators comment has no user")
        username = _required_string(user, "username")
        parent_id = _optional_string(
            item.get("parent_comment_id")
            or item.get("replied_to_comment_id")
            or item.get("parent_id")
        )
        if parent_id is None and isinstance(item.get("parent"), dict):
            parent_id = _optional_string(item["parent"].get("id") or item["parent"].get("pk"))
        return public_record(InstagramComment(
            platform_comment_id=_required_string(item, "id"),
            platform_user_id=_optional_string(user.get("id") or user.get("pk")),
            username=username,
            display_name=_optional_string(user.get("full_name")),
            profile_url=f"https://www.instagram.com/{username}/",
            text=_required_string(item, "text", allow_empty=True),
            created_at=parse_datetime(item.get("created_at")),
            parent_platform_comment_id=parent_id,
        ))


def _required_string(item: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = item.get(key)
    if value is None or (not allow_empty and value == ""):
        raise ProviderResponseError(f"ScrapeCreators response field {key!r} is missing")
    return str(value)


def _optional_string(value: object) -> str | None:
    return None if value in (None, "") else str(value)


def _optional_nonnegative_int(value: object) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None

