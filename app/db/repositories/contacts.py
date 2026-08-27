from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Contact, ContactEvent, ContactEventType
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
        if platform_user_id:
            by_id = await self.session.scalar(
                select(Contact).where(
                    Contact.platform == platform,
                    Contact.platform_user_id == platform_user_id,
                )
            )
            if by_id is not None:
                return by_id
            by_username = await self._find_by_username(platform, normalized)
            if by_username is not None and by_username.platform_user_id is not None:
                return None
            return by_username
        return await self._find_by_username(platform, normalized)

    async def _find_by_username(self, platform: str, normalized: str) -> Contact | None:
        return await self.session.scalar(
            select(Contact).where(
                Contact.platform == platform,
                Contact.normalized_username == normalized,
            )
        )

    async def upsert_from_comment(
        self, comment: InstagramComment, platform: str = "instagram"
    ) -> tuple[Contact, bool]:
        now = datetime.now(UTC)
        normalized = normalize_username(comment.username)
        contact = await self.find(platform, comment.platform_user_id, normalized)
        username_owner = await self._find_by_username(platform, normalized)
        if (
            comment.platform_user_id
            and username_owner is not None
            and username_owner is not contact
            and username_owner.platform_user_id != comment.platform_user_id
        ):
            previous_normalized = username_owner.normalized_username
            username_owner.normalized_username = (
                f"__previous__:{username_owner.id}:{previous_normalized}"
            )[:255]
            self.session.add(
                ContactEvent(
                    contact_id=username_owner.id,
                    event_type=ContactEventType.CONTACT_IDENTITY_CHANGED,
                    payload_json={
                        "reason": "username_reassigned_to_different_platform_user_id",
                        "previous_normalized_username": previous_normalized,
                        "new_platform_user_id": comment.platform_user_id,
                    },
                )
            )
            await self.session.flush()
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
