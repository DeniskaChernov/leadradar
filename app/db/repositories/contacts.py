from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Contact
from app.schemas.instagram import InstagramComment


def normalize_username(username: str) -> str:
    return username.strip().lower().lstrip("@").rstrip("/")


class ContactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find(
        self, platform: str, platform_user_id: str | None, username: str
    ) -> Contact | None:
        normalized = normalize_username(username)
        predicates = [Contact.normalized_username == normalized]
        if platform_user_id:
            predicates.insert(0, Contact.platform_user_id == platform_user_id)
        return await self.session.scalar(
            select(Contact).where(Contact.platform == platform, or_(*predicates))
        )

    async def upsert_from_comment(
        self, comment: InstagramComment, platform: str = "instagram"
    ) -> tuple[Contact, bool]:
        now = datetime.now(UTC)
        normalized = normalize_username(comment.username)
        contact = await self.find(platform, comment.platform_user_id, normalized)
        created = contact is None
        if contact is None:
            contact = Contact(
                platform=platform,
                platform_user_id=comment.platform_user_id,
                username=normalized,
                normalized_username=normalized,
                display_name=comment.display_name,
                profile_url=comment.profile_url,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(contact)
        else:
            if comment.platform_user_id and not contact.platform_user_id:
                contact.platform_user_id = comment.platform_user_id
            contact.username = normalized
            contact.normalized_username = normalized
            contact.display_name = comment.display_name or contact.display_name
            contact.profile_url = comment.profile_url
            contact.last_seen_at = now
        await self.session.flush()
        return contact, created

