from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.providers.base import InstagramProvider, ProviderError
from app.schemas.instagram import InstagramComment, InstagramPost, InstagramProfile

logger = logging.getLogger(__name__)
T = TypeVar("T")


class FallbackInstagramProvider(InstagramProvider):
    name = "fallback"

    def __init__(self, primary: InstagramProvider, fallback: InstagramProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    async def _call(
        self,
        operation: str,
        primary_call: Callable[[], Awaitable[T]],
        fallback_call: Callable[[], Awaitable[T]],
    ) -> T:
        try:
            return await primary_call()
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
        return await self._call(
            "get_comments",
            lambda: self.primary.get_comments(post),
            lambda: self.fallback.get_comments(post),
        )

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.fallback.aclose()

