"""Разрешённые slug аудиторий для agent/MCP — только ACTIVE registry definitions."""

from __future__ import annotations

from app.services.audience_registry import (
    ACTIVE_AUDIENCE_DEFINITIONS,
    AUDIENCE_BY_SLUG,
    AudienceDefinition,
)


class AllowedAudienceRegistry:
    """Gate для agent tools: только governed ACTIVE audiences из registry."""

    @classmethod
    def list_active(cls) -> tuple[AudienceDefinition, ...]:
        return ACTIVE_AUDIENCE_DEFINITIONS

    @classmethod
    def is_allowed(cls, slug: str) -> bool:
        normalized = (slug or "").strip().lower()
        if not normalized:
            return False
        definition = AUDIENCE_BY_SLUG.get(normalized)
        return definition is not None and definition.status == "ACTIVE"

    @classmethod
    def get(cls, slug: str) -> AudienceDefinition | None:
        normalized = (slug or "").strip().lower()
        if not cls.is_allowed(normalized):
            return None
        return AUDIENCE_BY_SLUG[normalized]

    @classmethod
    def require(cls, slug: str) -> AudienceDefinition:
        definition = cls.get(slug)
        if definition is None:
            raise ValueError(f"Audience slug is not allowed or not ACTIVE: {slug}")
        return definition
