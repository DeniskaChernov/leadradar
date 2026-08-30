from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.providers.base import InstagramProvider, ProviderError, ProviderUsageBlockedError
from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")


class FallbackInstagramProvider(InstagramProvider):
    def __init__(self, primary: InstagramProvider, fallback: InstagramProvider) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"

    def begin_cycle(self) -> None:
        # Both wrappers normally share one ScanBudget. Resetting twice is harmless and keeps this
        # adapter correct even when providers are configured independently.
        self.primary.begin_cycle()
        self.fallback.begin_cycle()

    def set_scan_budget_limit(self, limit: int) -> None:
        self.primary.set_scan_budget_limit(limit)
        self.fallback.set_scan_budget_limit(limit)

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
    ) -> CommentFetchResult:
        return await self._call(
            "get_comment_batch",
            lambda: self.primary.get_comment_batch(
                post,
                known_comment_ids=known_comment_ids,
                max_pages=max_pages,
            ),
            lambda: self.fallback.get_comment_batch(
                post,
                known_comment_ids=known_comment_ids,
                max_pages=max_pages,
            ),
        )

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.fallback.aclose()
