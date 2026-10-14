from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.providers.base import (
    InstagramProvider,
    ProviderCallUncertainError,
    ProviderError,
    ProviderUsageBlockedError,
)
from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
    PostFetchResult,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


class FallbackInstagramProvider(InstagramProvider):
    def __init__(self, primary: InstagramProvider, fallback: InstagramProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"

    @property
    def comment_cursor_provider(self) -> str:
        return self.primary.comment_cursor_provider

    @property
    def supports_comment_replies(self) -> bool:
        return self.primary.supports_comment_replies

    @property
    def reply_cursor_provider(self) -> str:
        return self.primary.reply_cursor_provider

    async def get_reply_batch(
        self, post: InstagramPost, parent_comment_id: str, *, cursor: str | None = None,
    ) -> CommentFetchResult:
        # Thread cursors and billing belong to primary; no unrelated paid fallback.
        return await self.primary.get_reply_batch(post, parent_comment_id, cursor=cursor)

    @property
    def supports_post_pagination(self) -> bool:
        return self.primary.supports_post_pagination

    @property
    def post_cursor_provider(self) -> str:
        return self.primary.post_cursor_provider

    async def get_post_page(self, handle: str, *, cursor: str | None = None) -> PostFetchResult:
        if cursor is not None:
            return await self.primary.get_post_page(handle, cursor=cursor)
        return await self._call(
            "get_post_page",
            lambda: self.primary.get_post_page(handle),
            lambda: self.fallback.get_post_page(handle),
        )

    def begin_cycle(self) -> None:
        # Both wrappers normally share one ScanBudget. Resetting twice is harmless and keeps this
        # adapter correct even when providers are configured independently.
        self.primary.begin_cycle()
        self.fallback.begin_cycle()

    def set_scan_budget_limit(self, limit: int) -> None:
        self.primary.set_scan_budget_limit(limit)
        self.fallback.set_scan_budget_limit(limit)

    def restore_default_scan_budget(self) -> None:
        self.primary.restore_default_scan_budget()
        self.fallback.restore_default_scan_budget()

    def scan_budget_status(self) -> dict[str, int] | None:
        return self.primary.scan_budget_status() or self.fallback.scan_budget_status()

    async def _call(
        self,
        operation: str,
        primary_call: Callable[[], Awaitable[T]],
        fallback_call: Callable[[], Awaitable[T]],
    ) -> T:
        try:
            return await primary_call()
        except ProviderUsageBlockedError:
            # Safety/budget blocks are intentional. Never bypass them by trying another paid API.
            raise
        except ProviderCallUncertainError:
            # Billing ambiguous after call_started — fallback would risk double spend.
            raise
        except ProviderError as exc:
            logger.warning(
                "provider_fallback_activated operation=%s primary=%s fallback=%s error_type=%s",
                operation,
                self.primary.name,
                self.fallback.name,
                type(exc).__name__,
            )
            return await fallback_call()

    async def get_profile(self, handle: str) -> InstagramProfile:
        return await self._call(
            "get_profile",
            lambda: self.primary.get_profile(handle),
            lambda: self.fallback.get_profile(handle),
        )

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        return await self._call(
            "get_reels",
            lambda: self.primary.get_reels(handle),
            lambda: self.fallback.get_reels(handle),
        )

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        return await self._call(
            "get_post",
            lambda: self.primary.get_post(url, competitor),
            lambda: self.fallback.get_post(url, competitor),
        )

    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        return (await self.get_comment_batch(post)).comments

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
        cursor: str | None = None,
    ) -> CommentFetchResult:
        if cursor is not None:
            # Cursors are opaque and provider-specific; never pass one to fallback.
            return await self.primary.get_comment_batch(
                post, known_comment_ids=known_comment_ids, max_pages=max_pages, cursor=cursor,
            )
        return await self._call(
            "get_comment_batch",
            lambda: self.primary.get_comment_batch(
                post,
                known_comment_ids=known_comment_ids,
                max_pages=max_pages,
                cursor=cursor,
            ),
            lambda: self.fallback.get_comment_batch(
                post,
                known_comment_ids=known_comment_ids,
                max_pages=max_pages,
                cursor=cursor,
            ),
        )

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.fallback.aclose()
