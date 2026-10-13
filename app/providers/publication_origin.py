"""Keep locally generated demo publications out of paid provider traffic."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.providers.base import ProviderUsageBlockedError
from app.schemas.instagram import InstagramPost

_FIXTURE_ID = re.compile(r"^(?:mock|demo|fixture|replay)[-_]", re.IGNORECASE)
_LIVE_PROVIDERS = frozenset({"scrapecreators", "brightdata"})


class FixturePublicationError(ProviderUsageBlockedError):
    """Local sample data cannot trigger a paid call or a provider fallback."""


def uses_live_provider(name: str) -> bool:
    return bool(_LIVE_PROVIDERS.intersection(name.lower().split("+")))


def is_fixture_url(url: str) -> bool:
    parts = urlsplit(url).path.strip("/").split("/")
    return len(parts) >= 2 and parts[0] in {"p", "reel", "reels", "tv"} and bool(
        _FIXTURE_ID.match(parts[1])
    )


def is_fixture_publication(post: InstagramPost) -> bool:
    raw = post.raw_data or {}
    origin = str(raw.get("source") or raw.get("provider") or "").lower()
    return (
        origin in {"mock", "replay", "demo", "fixture"}
        or bool(_FIXTURE_ID.match(post.platform_post_id))
        or is_fixture_url(post.url)
    )
