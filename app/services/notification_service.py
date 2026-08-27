from __future__ import annotations

from typing import Protocol


class LeadNotifier(Protocol):
    async def notify_new_signal(self, lead_id: int) -> int: ...

    async def notify_analyzed_lead(self, lead_id: int) -> int: ...

    async def notify_hot_lead(self, lead_id: int) -> int: ...

    async def notify_significant_change(self, change_id: int) -> int: ...

    async def flush_pending(self) -> int: ...


class NullLeadNotifier:
    async def notify_new_signal(self, lead_id: int) -> int:
        return 0

    async def notify_analyzed_lead(self, lead_id: int) -> int:
        return 0

    async def notify_hot_lead(self, lead_id: int) -> int:
        return 0

    async def notify_significant_change(self, change_id: int) -> int:
        return 0

    async def flush_pending(self) -> int:
        return 0
