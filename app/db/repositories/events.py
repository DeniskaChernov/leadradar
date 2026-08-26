from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContactEvent, ContactEventType


class ContactEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        contact_id: int,
        event_type: ContactEventType,
        *,
        lead_id: int | None = None,
        deal_id: int | None = None,
        manager_telegram_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ContactEvent:
        event = ContactEvent(
            contact_id=contact_id,
            event_type=event_type,
            lead_id=lead_id,
            deal_id=deal_id,
            manager_telegram_id=manager_telegram_id,
            payload_json=payload or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event

