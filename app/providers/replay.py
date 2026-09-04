from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.providers.base import InstagramProvider, ProviderResponseError
from app.schemas.instagram import (
    CommentFetchResult,
    InstagramComment,
    InstagramPost,
    InstagramProfile,
)


@dataclass(frozen=True, slots=True)
class ReplayStatus:
    step: int
    total_steps: int
    title: str
    description: str
    can_advance: bool


class ReplayScenario:
    """Persistent deterministic scenario used to test the whole product without paid APIs."""

    def __init__(self, fixture_path: str | Path, state_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)
        self.state_path = Path(state_path)
        self.data = self._load_fixture()

    def _load_fixture(self) -> dict[str, Any]:
        if not self.fixture_path.exists():
            raise ProviderResponseError(f"Replay fixture not found: {self.fixture_path}")
        try:
            payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderResponseError("Replay fixture is invalid JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
            raise ProviderResponseError("Replay fixture has no steps list")
        return payload

    @property
    def step(self) -> int:
        if not self.state_path.exists():
            return 0
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            value = int(payload.get("step", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0
        return max(0, min(value, max(0, len(self.steps) - 1)))

    @property
    def steps(self) -> list[dict[str, Any]]:
        return [item for item in self.data.get("steps", []) if isinstance(item, dict)]

    def status(self) -> ReplayStatus:
        if not self.steps:
            return ReplayStatus(0, 0, "Сценарий пуст", "", False)
        current = self.steps[self.step]
        return ReplayStatus(
            step=self.step,
            total_steps=len(self.steps),
            title=str(current.get("title") or f"Шаг {self.step + 1}"),
            description=str(current.get("description") or ""),
            can_advance=self.step < len(self.steps) - 1,
        )

    def advance(self) -> ReplayStatus:
        target = min(self.step + 1, max(0, len(self.steps) - 1))
        self._write_step(target)
        return self.status()

    def reset(self) -> ReplayStatus:
        self._write_step(0)
        return self.status()

    def _write_step(self, step: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"step": step}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_path)

    def competitor(self, handle: str) -> dict[str, Any]:
        normalized = handle.strip().lower().lstrip("@")
        competitors = self.data.get("competitors") or {}
        item = competitors.get(normalized) if isinstance(competitors, dict) else None
        if not isinstance(item, dict):
            raise ProviderResponseError(f"Replay has no competitor @{normalized}")
        return item

    def visible_count(self, post_id: str) -> int:
        if not self.steps:
            return 0
        visible = self.steps[self.step].get("visible_comments") or {}
        try:
            return max(0, int(visible.get(post_id, 0)))
        except (TypeError, ValueError):
            return 0


class ReplayInstagramProvider(InstagramProvider):
    name = "replay"

    def __init__(self, fixture_path: str | Path, state_path: str | Path) -> None:
        self.scenario = ReplayScenario(fixture_path, state_path)

    async def get_profile(self, handle: str) -> InstagramProfile:
        row = self.scenario.competitor(handle).get("profile")
        if not isinstance(row, dict):
            raise ProviderResponseError("Replay profile is missing")
        return InstagramProfile.model_validate(row)

    async def get_reels(self, handle: str) -> list[InstagramPost]:
        competitor = handle.strip().lower().lstrip("@")
        rows = self.scenario.competitor(competitor).get("reels") or []
        result: list[InstagramPost] = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("post"), dict):
                continue
            payload = dict(row["post"])
            post_id = str(payload.get("platform_post_id") or "")
            payload.update(
                competitor=competitor,
                comments_count=self.scenario.visible_count(post_id),
                raw_data={"source": "replay", "step": self.scenario.step},
            )
            result.append(InstagramPost.model_validate(payload))
        return result

    async def get_post(self, url: str, competitor: str) -> InstagramPost:
        for post in await self.get_reels(competitor):
            if post.url == url:
                return post
        raise ProviderResponseError(f"Replay post not found: {url}")

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
        rows = self.scenario.competitor(post.competitor).get("reels") or []
        for row in rows:
            payload = row.get("post") if isinstance(row, dict) else None
            if not isinstance(payload, dict) or str(payload.get("platform_post_id")) != post.platform_post_id:
                continue
            comments = row.get("comments") or []
            visible = self.scenario.visible_count(post.platform_post_id)
            normalized = [
                InstagramComment.model_validate({**item, "raw_data": {"source": "replay"}})
                for item in comments[:visible]
                if isinstance(item, dict)
            ]
            return CommentFetchResult(
                comments=normalized,
                provider=self.name,
                pages_fetched=1,
                coverage_status="FULL",
                cursor_exhausted=True,
            )
        raise ProviderResponseError(f"Replay comments not found: {post.platform_post_id}")
