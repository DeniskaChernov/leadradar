from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    BusinessAlias,
    BusinessAliasType,
    BusinessEntity,
    BusinessEntityStatus,
    Evidence,
    Vertical,
)


class EntityResolutionError(RuntimeError):
    pass


class EntityResolutionConflict(EntityResolutionError):
    pass


STRONG_ALIAS_TYPES = {
    BusinessAliasType.DOMAIN,
    BusinessAliasType.GOOGLE_PLACE_ID,
    BusinessAliasType.PUBLIC_PHONE,
    BusinessAliasType.MARKETPLACE_SELLER_ID,
}


@dataclass(frozen=True, slots=True)
class AliasCandidate:
    alias_type: BusinessAliasType
    value: str
    source_url: str | None = None
    evidence_id: int | None = None
    confidence: int = 50
    verified: bool = False


class EntityResolutionService:
    """Resolve businesses only from explicit stable public identifiers.

    Similar names, bios and visual resemblance are intentionally never auto-merge keys.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def resolve(
        self,
        *,
        canonical_key: str,
        canonical_name: str,
        verticals: set[Vertical],
        aliases: list[AliasCandidate],
    ) -> BusinessEntity:
        if not canonical_key.strip() or not canonical_name.strip():
            raise EntityResolutionError("canonical key and name are required")
        if not verticals:
            raise EntityResolutionError("at least one vertical is required")
        normalized_aliases = [
            (candidate, self.normalize_alias(candidate.alias_type, candidate.value))
            for candidate in aliases
        ]
        if any(not value for _candidate, value in normalized_aliases):
            raise EntityResolutionError("empty alias is not allowed")

        async with self.session_factory() as session:
            await self._validate_evidence(session, aliases)
            matched = await self._strong_matches(session, normalized_aliases)
            by_key = await session.scalar(
                select(BusinessEntity).where(
                    BusinessEntity.canonical_key == canonical_key.strip()
                )
            )
            candidates = {item.id: item for item in matched}
            if by_key is not None:
                candidates[by_key.id] = by_key
            if len(candidates) > 1:
                raise EntityResolutionConflict(
                    "strong public identifiers point to different businesses"
                )
            business = next(iter(candidates.values()), None)
            if business is None:
                business = BusinessEntity(
                    canonical_key=canonical_key.strip(),
                    canonical_name=canonical_name.strip(),
                    normalized_name=self.normalize_name(canonical_name),
                    verticals_json=sorted(item.value for item in verticals),
                    entity_status=BusinessEntityStatus.NEEDS_VERIFICATION,
                    confidence=50,
                )
                session.add(business)
                await session.flush()
            else:
                business.verticals_json = sorted(
                    set(business.verticals_json).union(item.value for item in verticals)
                )

            for candidate, normalized in normalized_aliases:
                existing = await session.scalar(
                    select(BusinessAlias).where(
                        BusinessAlias.business_id == business.id,
                        BusinessAlias.alias_type == candidate.alias_type,
                        BusinessAlias.normalized_value == normalized,
                    )
                )
                if existing is None:
                    session.add(
                        BusinessAlias(
                            business_id=business.id,
                            alias_type=candidate.alias_type,
                            value=candidate.value.strip(),
                            normalized_value=normalized,
                            source_url=candidate.source_url,
                            evidence_id=candidate.evidence_id,
                            confidence=max(0, min(100, candidate.confidence)),
                            verified=candidate.verified,
                        )
                    )
                else:
                    existing.confidence = max(existing.confidence, candidate.confidence)
                    existing.verified = existing.verified or candidate.verified
                    existing.source_url = existing.source_url or candidate.source_url
                    existing.evidence_id = existing.evidence_id or candidate.evidence_id
            if any(
                candidate.verified and candidate.alias_type in STRONG_ALIAS_TYPES
                for candidate in aliases
            ):
                business.entity_status = BusinessEntityStatus.VERIFIED
                business.confidence = max(
                    business.confidence,
                    max(
                        candidate.confidence
                        for candidate in aliases
                        if candidate.verified
                        and candidate.alias_type in STRONG_ALIAS_TYPES
                    ),
                )
            await session.commit()
            return business

    @staticmethod
    async def _validate_evidence(
        session: AsyncSession, aliases: list[AliasCandidate]
    ) -> None:
        requested = {item.evidence_id for item in aliases if item.evidence_id is not None}
        if not requested:
            return
        found = set(
            await session.scalars(select(Evidence.id).where(Evidence.id.in_(requested)))
        )
        missing = requested - found
        if missing:
            raise EntityResolutionError(
                f"unknown evidence IDs: {', '.join(map(str, sorted(missing)))}"
            )

    @staticmethod
    async def _strong_matches(
        session: AsyncSession,
        aliases: list[tuple[AliasCandidate, str]],
    ) -> list[BusinessEntity]:
        predicates = [
            (candidate.alias_type, normalized)
            for candidate, normalized in aliases
            if candidate.verified and candidate.alias_type in STRONG_ALIAS_TYPES
        ]
        matched: dict[int, BusinessEntity] = {}
        for alias_kind, normalized in predicates:
            rows = list(
                await session.scalars(
                    select(BusinessEntity)
                    .join(BusinessAlias, BusinessAlias.business_id == BusinessEntity.id)
                    .where(
                        BusinessAlias.alias_type == alias_kind,
                        BusinessAlias.normalized_value == normalized,
                        BusinessAlias.verified.is_(True),
                    )
                )
            )
            matched.update({row.id: row for row in rows})
        return list(matched.values())

    @staticmethod
    def normalize_name(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().casefold())

    @staticmethod
    def normalize_alias(alias_type: BusinessAliasType, value: str) -> str:
        cleaned = value.strip()
        if alias_type == BusinessAliasType.DOMAIN:
            parsed = urlparse(
                cleaned if "://" in cleaned else f"https://{cleaned}"
            )
            return (parsed.hostname or "").casefold().removeprefix("www.").rstrip(".")
        if alias_type in {
            BusinessAliasType.INSTAGRAM_HANDLE,
            BusinessAliasType.PUBLIC_TELEGRAM,
        }:
            return cleaned.casefold().lstrip("@").rstrip("/")
        if alias_type == BusinessAliasType.PUBLIC_PHONE:
            digits = re.sub(r"\D", "", cleaned)
            return f"+{digits}" if digits else ""
        return re.sub(r"\s+", " ", cleaned.casefold())
