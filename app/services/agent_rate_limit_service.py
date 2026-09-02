"""Ограничение частоты запросов к AI-агенту на менеджера."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class AgentRateLimitResult:
    allowed: bool
    retry_after_seconds: int
    remaining: int


class AgentRateLimitService:
    def __init__(self, *, max_requests: int = 24, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[int, deque[datetime]] = {}

    def check(self, manager_id: int, *, now: datetime | None = None) -> AgentRateLimitResult:
        moment = now or datetime.now(UTC)
        bucket = self._hits.setdefault(manager_id, deque())
        cutoff = moment - timedelta(seconds=self.window_seconds)
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            retry_after = int((bucket[0] + timedelta(seconds=self.window_seconds) - moment).total_seconds()) + 1
            return AgentRateLimitResult(False, max(retry_after, 1), 0)
        bucket.append(moment)
        return AgentRateLimitResult(True, 0, self.max_requests - len(bucket))


agent_rate_limiter = AgentRateLimitService()
