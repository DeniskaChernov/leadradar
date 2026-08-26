from __future__ import annotations

from typing import Protocol


class LeadNotifier(Protocol):
    async def notify_hot_lead(self, lead_id: int) -> None: ...


class NullLeadNotifier:
    async def notify_hot_lead(self, lead_id: int) -> None:
        return None

