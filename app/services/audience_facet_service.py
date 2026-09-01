from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from app.db.models import AudienceMembership, Contact, ContactIntelligence


@dataclass(frozen=True, slots=True)
class AudienceFacetQuery:
    vertical: str | None = None
    product_family: str | None = None
    intent: str | None = None
    buyer_role: str | None = None
    commercial_stage: str | None = None
    quantity_band: str | None = None
    city: str | None = None
    source_competitor: str | None = None
    recency_bucket: str | None = None
    confidence_band: str | None = None
    value_band: str | None = None
    purchase_horizon: str | None = None
    rattan_layer: str | None = None
    rattan_role: str | None = None
    manager_status: str | None = None
    won_status: str | None = None

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> AudienceFacetQuery:
        return cls(
            **{
                name: (str(values.get(name) or "").strip() or None)
                for name in cls.__dataclass_fields__
            }
        )

    @property
    def active(self) -> dict[str, str]:
        return {
            name: value
            for name, value in ((name, getattr(self, name)) for name in self.__dataclass_fields__)
            if value is not None
        }

    @staticmethod
    def _band(value: int, band: str) -> bool:
        normalized = band.upper()
        return (
            (normalized == "LOW" and value < 40)
            or (normalized == "MEDIUM" and 40 <= value < 70)
            or (normalized == "HIGH" and value >= 70)
        )

    def matches(
        self,
        membership: AudienceMembership,
        contact: Contact,
        intelligence: ContactIntelligence,
        *,
        source_competitors: set[str] | None = None,
        rattan_layers: set[str] | None = None,
        rattan_roles: set[str] | None = None,
        won_statuses: set[str] | None = None,
        now: datetime | None = None,
    ) -> bool:
        products = {str(item.get("value")) for item in intelligence.product_interests_json}
        intents = {str(item.get("value")) for item in intelligence.top_intents_json}
        checks = [
            not self.vertical or intelligence.vertical == self.vertical,
            not self.product_family or self.product_family in products,
            not self.intent or self.intent in intents,
            not self.buyer_role or intelligence.primary_buyer_role == self.buyer_role,
            not self.commercial_stage or intelligence.commercial_stage == self.commercial_stage,
            not self.quantity_band or intelligence.quantity_band == self.quantity_band,
            not self.city or (contact.city or "").casefold() == self.city.casefold(),
            not self.source_competitor
            or self.source_competitor.casefold()
            in {value.casefold() for value in source_competitors or set()},
            not self.confidence_band or self._band(membership.confidence, self.confidence_band),
            not self.value_band or self._band(intelligence.value_score, self.value_band),
            not self.purchase_horizon or intelligence.purchase_horizon == self.purchase_horizon,
            not self.rattan_layer or self.rattan_layer in (rattan_layers or set()),
            not self.rattan_role or self.rattan_role in (rattan_roles or set()),
            not self.manager_status
            or (
                self.manager_status.upper() == "ASSIGNED"
                and contact.assigned_manager_telegram_id is not None
            )
            or (
                self.manager_status.upper() == "UNASSIGNED"
                and contact.assigned_manager_telegram_id is None
            ),
            not self.won_status or self.won_status in (won_statuses or set()),
        ]
        if self.recency_bucket:
            reference = now or datetime.now(UTC)
            last_seen = intelligence.last_seen_at
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            days = max(0, (reference - last_seen).days)
            checks.append(
                (self.recency_bucket == "0_7" and days <= 7)
                or (self.recency_bucket == "8_30" and 8 <= days <= 30)
                or (self.recency_bucket == "31_PLUS" and days >= 31)
            )
        return all(checks)
