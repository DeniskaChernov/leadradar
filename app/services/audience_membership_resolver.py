"""Read-only resolver активных membership и evidence из БД."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AudienceMembership, AudienceSegment, Contact
from app.services.allowed_audience_registry import AllowedAudienceRegistry


@dataclass(frozen=True, slots=True)
class ResolvedAudienceMembership:
    segment_slug: str
    segment_name: str
    contact_id: int
    confidence: int
    evidence_ids: tuple[int, ...]
    reasons: tuple[str, ...]
    evaluated_at: datetime | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ContactAudienceSnapshot:
    contact_id: int
    username: str
    memberships: tuple[ResolvedAudienceMembership, ...]
    evidence_ids: tuple[int, ...]


class AudienceMembershipResolver:
    """Возвращает только ACTIVE registry audiences и persisted evidence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def resolve_contact(self, contact_id: int) -> ContactAudienceSnapshot | None:
        async with self.session_factory() as session:
            contact = await session.get(Contact, contact_id)
            if contact is None:
                return None
            rows = (
                await session.execute(
                    select(AudienceMembership, AudienceSegment)
                    .join(AudienceSegment, AudienceSegment.id == AudienceMembership.segment_id)
                    .where(
                        AudienceMembership.contact_id == contact_id,
                        AudienceMembership.active.is_(True),
                        AudienceSegment.status == "ACTIVE",
                        AudienceSegment.active.is_(True),
                    )
                    .order_by(AudienceSegment.name)
                )
            ).all()

        memberships: list[ResolvedAudienceMembership] = []
        evidence_ids: set[int] = set()
        for membership, segment in rows:
            if not AllowedAudienceRegistry.is_allowed(segment.slug):
                continue
            ids = tuple(sorted(set(membership.evidence_ids_json or [])))
            evidence_ids.update(ids)
            memberships.append(
                ResolvedAudienceMembership(
                    segment_slug=segment.slug,
                    segment_name=segment.name,
                    contact_id=contact_id,
                    confidence=membership.confidence,
                    evidence_ids=ids,
                    reasons=tuple(membership.evidence_json or []),
                    evaluated_at=membership.evaluated_at,
                    expires_at=membership.expires_at,
                )
            )
        return ContactAudienceSnapshot(
            contact_id=contact_id,
            username=contact.username,
            memberships=tuple(memberships),
            evidence_ids=tuple(sorted(evidence_ids)),
        )
