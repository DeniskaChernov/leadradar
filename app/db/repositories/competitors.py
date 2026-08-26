from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import normalize_instagram_handle
from app.db.models import Competitor


class CompetitorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_handle(self, handle: str) -> Competitor | None:
        normalized = normalize_instagram_handle(handle)
        return await self.session.scalar(
            select(Competitor).where(Competitor.normalized_handle == normalized)
        )

    async def get_or_create(self, handle: str) -> Competitor:
        normalized = normalize_instagram_handle(handle)
        competitor = await self.get_by_handle(normalized)
        if competitor is None:
            competitor = Competitor(handle=handle, normalized_handle=normalized)
            self.session.add(competitor)
            await self.session.flush()
        return competitor

