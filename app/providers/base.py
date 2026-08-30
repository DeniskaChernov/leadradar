from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
    ProviderCreditObservation,
)

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """Base error for a provider failure that may trigger fallback."""


class ProviderAuthError(ProviderError):
    """Provider credentials are missing or rejected."""


class ProviderResponseError(ProviderError):
    """Provider returned an invalid or unsupported response."""


class ProviderUsageBlockedError(ProviderError):
    """External usage is intentionally blocked by a safety/budget guard.

    This is different from a transient provider failure and must not trigger fallback,
    otherwise a safety block on the primary provider could immediately attempt the fallback.
    """


class InstagramProvider(ABC):
    name: str

    def begin_cycle(self) -> None:
        """Reset optional per-cycle state before one monitoring pass.

        Mock/replay providers do not need it. Live wrappers use it to reset the
        conservative request budget that protects external credits.
        """
        return None

    def set_scan_budget_limit(self, limit: int) -> None:
        """Установить durable-проверенный лимит текущего ручного запуска."""
        return None

    def scan_budget_status(self) -> dict[str, int] | None:
        return None

    @abstractmethod
    async def get_profile(self, handle: str) -> InstagramProfile:
        raise NotImplementedError

    @abstractmethod
    async def get_reels(self, handle: str) -> list[InstagramPost]:
        raise NotImplementedError

    @abstractmethod
    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        raise NotImplementedError

    @abstractmethod
    async def get_comments(self, post: InstagramPost) -> list[InstagramComment]:
        raise NotImplementedError

    async def get_comment_batch(
        self,
        post: InstagramPost,
        *,
        known_comment_ids: set[str] | None = None,
        max_pages: int | None = None,
    ) -> CommentFetchResult:
        comments = await self.get_comments(post)
        return CommentFetchResult(
            comments=comments,
            provider=self.name,
            pages_fetched=1,
            coverage_status="UNKNOWN",
            cursor_exhausted=True,
        )

    async def aclose(self) -> None:
        return None

    def pop_credit_observations(self) -> list[ProviderCreditObservation]:
        """Вернуть provider-confirmed credit facts, накопленные последним вызовом."""
        return []


class HTTPInstagramProvider(InstagramProvider):
    def __init__(
        self,
        *,
        timeout_seconds: float = 25,
        max_attempts: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = await self.client.request(method, url, **kwargs)
                if response.status_code in {401, 402, 403}:
                    raise ProviderAuthError(
                        f"{self.name} authentication failed ({response.status_code})"
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    raise ProviderError(f"{self.name} temporary HTTP {response.status_code}")
                response.raise_for_status()
                return response.json()
            except ProviderAuthError:
                raise
            except (httpx.HTTPError, ValueError, ProviderError) as exc:
                last_error = exc
                logger.warning(
                    "provider_request_failed provider=%s attempt=%s error_type=%s",
                    self.name,
                    attempt,
                    type(exc).__name__,
                )
                if attempt < self.max_attempts:
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        raise ProviderError(
            f"{self.name} request failed after {self.max_attempts} attempts"
        ) from last_error

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()


def parse_datetime(value: object) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        from datetime import UTC, datetime

        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str):
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ProviderResponseError("Unsupported timestamp type")
