from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AudienceMembership,
    AudienceSegment,
    Comment,
    Contact,
    ContactIntelligence,
    ExportEligibility,
    Lead,
    LeadStatus,
)


@dataclass(frozen=True, slots=True)
class SegmentDefinition:
    slug: str
    name: str
    description: str
    criteria: dict[str, object]


SEGMENTS = (
    SegmentDefinition(
        "hot-24h",
        "Горячие покупатели · 24 часа",
        "HOT-сигналы за последние сутки.",
        {"hot": True, "days": 1},
    ),
    SegmentDefinition(
        "hot-7d",
        "Горячие покупатели · 7 дней",
        "HOT-сигналы за последние 7 дней.",
        {"hot": True, "days": 7},
    ),
    SegmentDefinition(
        "hot-30d",
        "Горячие покупатели · 30 дней",
        "HOT-сигналы за последние 30 дней.",
        {"hot": True, "days": 30},
    ),
    SegmentDefinition(
        "dining-sets",
        "Обеденные комплекты",
        "Наблюдаемый интерес к обеденным комплектам.",
        {"product": "DINING_SET"},
    ),
    SegmentDefinition("tables", "Столы", "Наблюдаемый интерес к столам.", {"product": "TABLE"}),
    SegmentDefinition(
        "chairs",
        "Стулья и кресла",
        "Наблюдаемый интерес к стульям и креслам.",
        {"product": "CHAIRS"},
    ),
    SegmentDefinition(
        "outdoor",
        "Outdoor",
        "Наблюдаемый спрос на садовую и террасную мебель.",
        {"product": "OUTDOOR_FURNITURE"},
    ),
    SegmentDefinition(
        "rattan",
        "Плетёная мебель",
        "Наблюдаемый интерес к плетёной мебели и ротангу.",
        {"product": "RATTAN_FURNITURE"},
    ),
    SegmentDefinition(
        "asked-price", "Спрашивали цену", "Контакты с явным вопросом о цене.", {"intent": "PRICE"}
    ),
    SegmentDefinition(
        "asked-availability",
        "Спрашивали наличие",
        "Контакты с вопросом о наличии.",
        {"intent": "AVAILABILITY"},
    ),
    SegmentDefinition(
        "asked-delivery",
        "Спрашивали доставку",
        "Контакты с вопросом о доставке.",
        {"intent": "DELIVERY"},
    ),
    SegmentDefinition(
        "asked-quantity",
        "Спрашивали количество",
        "Контакты с количеством или оптовым запросом.",
        {"intent": "QUANTITY"},
    ),
    SegmentDefinition(
        "multi-competitor-2",
        "Сравнивают 2+ конкурентов",
        "Спрос обнаружен минимум у двух продавцов.",
        {"sources": 2},
    ),
    SegmentDefinition(
        "multi-competitor-3",
        "Сравнивают 3+ конкурентов",
        "Спрос обнаружен минимум у трёх продавцов.",
        {"sources": 3},
    ),
    SegmentDefinition(
        "b2b", "B2B и HoReCa", "Явные оптовые или коммерческие признаки.", {"customer_type": "B2B"}
    ),
    SegmentDefinition(
        "quantity-20", "Количество 20+", "Явно указано не менее 20 единиц.", {"quantity": 20}
    ),
    SegmentDefinition(
        "quantity-50", "Количество 50+", "Явно указано не менее 50 единиц.", {"quantity": 50}
    ),
    SegmentDefinition(
        "reactivated",
        "Старые лиды снова активны",
        "Новый сигнал после перерыва не менее 30 дней.",
        {"reactivated": True, "days": 30},
    ),
    SegmentDefinition(
        "rattan-wholesale",
        "Ротанг · оптовый спрос",
        "Ротанг вместе с явным B2B или оптовым интересом.",
        {"product": "RATTAN_FURNITURE", "customer_type": "B2B"},
    ),
    SegmentDefinition(
        "rattan-high-value",
        "Ротанг · высокий потенциал",
        "Ротанг с высокой наблюдаемой коммерческой ценностью.",
        {"product": "RATTAN_FURNITURE", "min_value": 75},
    ),
)


class AudienceEngine:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], hot_threshold: int
    ) -> None:
        self.session_factory = session_factory
        self.hot_threshold = hot_threshold

    async def sync_segments(self) -> int:
        changed = 0
        async with self.session_factory() as session:
            for definition in SEGMENTS:
                segment = await session.scalar(
                    select(AudienceSegment).where(AudienceSegment.slug == definition.slug)
                )
                if segment is None:
                    session.add(
                        AudienceSegment(
                            slug=definition.slug,
                            name=definition.name,
                            description=definition.description,
                            criteria_json=definition.criteria,
                        )
                    )
                    changed += 1
                else:
                    before = (
                        segment.name,
                        segment.description,
                        segment.criteria_json,
                        segment.active,
                    )
                    segment.name = definition.name
                    segment.description = definition.description
                    segment.criteria_json = definition.criteria
                    segment.active = True
                    changed += int(
                        before
                        != (
                            segment.name,
                            segment.description,
                            segment.criteria_json,
                            segment.active,
                        )
                    )
            await session.commit()
        return changed

    async def recalculate_all(self) -> int:
        await self.sync_segments()
        async with self.session_factory() as session:
            contact_ids = list(await session.scalars(select(Contact.id).order_by(Contact.id)))
        for contact_id in contact_ids:
            await self.recalculate_contact(contact_id)
        return len(contact_ids)

    async def recalculate_contact(self, contact_id: int) -> ContactIntelligence:
        await self.sync_segments()
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            contact = await session.get(Contact, contact_id)
            if contact is None:
                raise ValueError(f"Contact {contact_id} was not found")
            rows = (
                await session.execute(
                    select(Lead, Comment)
                    .join(Comment, Comment.id == Lead.comment_id)
                    .where(Lead.contact_id == contact_id)
                    .order_by(Comment.discovered_at)
                )
            ).all()
            comments = list(
                await session.scalars(
                    select(Comment)
                    .where(Comment.contact_id == contact_id)
                    .order_by(Comment.discovered_at)
                )
            )
            intelligence = await session.scalar(
                select(ContactIntelligence).where(ContactIntelligence.contact_id == contact_id)
            )
            if intelligence is None:
                intelligence = ContactIntelligence(
                    contact_id=contact_id,
                    first_seen_at=contact.first_seen_at,
                    last_seen_at=contact.last_seen_at,
                )
                session.add(intelligence)

            commercial = [
                (lead, comment)
                for lead, comment in rows
                if lead.status != LeadStatus.NOT_LEAD and lead.lead_score >= 50
            ]
            sources = {comment.competitor_id for comment in comments}
            product_counts = Counter(
                lead.product_category for lead, _comment in commercial if lead.product_category
            )
            intent_counts = Counter(lead.intent for lead, _comment in commercial)
            raw_text = " ".join(comment.text.lower() for comment in comments)
            explicit_quantity = max(
                self._extract_explicit_quantities(raw_text),
                default=contact.desired_quantity or 0,
            )
            b2b_markers = (
                "оптом",
                "wholesale",
                "ulgurji",
                "кафе",
                "ресторан",
                "гостиниц",
                "kafe",
                "restoran",
                "mehmonxona",
                "производ",
                "перепрод",
                "дилер",
            )
            is_b2b = (
                explicit_quantity >= 20
                or any(marker in raw_text for marker in b2b_markers)
                or "HORECA" in product_counts
            )
            dates = [self._aware(comment.discovered_at) for comment in comments]
            first_seen = min(dates, default=self._aware(contact.first_seen_at))
            last_seen = max(dates, default=self._aware(contact.last_seen_at))
            recency_days = max(0, (now - last_seen).days)
            score_values = [lead.lead_score for lead, _comment in commercial]
            max_score = max(score_values, default=0)
            source_bonus = min(18, max(0, len(sources) - 1) * 9)
            activity_score = min(
                100,
                len(comments) * 8
                + len(commercial) * 10
                + source_bonus
                + (20 if recency_days <= 7 else 8 if recency_days <= 30 else 0),
            )
            value_score = min(
                100,
                max_score + (10 if is_b2b else 0) + (8 if explicit_quantity >= 20 else 0),
            )
            fit_score = min(100, max_score + min(12, len(product_counts) * 4))
            stage_order = {
                "NON_COMMERCIAL": 0,
                "AWARENESS": 1,
                "CONSIDERATION": 2,
                "PURCHASE_INTENT": 3,
                "READY_TO_BUY": 4,
            }
            stages = [
                str((lead.analysis_details or {}).get("funnel_stage") or "NON_COMMERCIAL")
                for lead, _comment in rows
            ]
            commercial_stage = max(
                stages, key=lambda item: stage_order.get(item, 0), default="NON_COMMERCIAL"
            )
            horizons = [
                str((lead.analysis_details or {}).get("purchase_horizon"))
                for lead, _comment in reversed(rows)
                if (lead.analysis_details or {}).get("purchase_horizon") not in (None, "UNKNOWN")
            ]
            intelligence.vertical = (
                "ARTIFICIAL_RATTAN" if "RATTAN_FURNITURE" in product_counts else "FURNITURE"
            )
            intelligence.commercial_stage = commercial_stage
            intelligence.intent_strength = max_score
            intelligence.signal_count = len(comments)
            intelligence.commercial_signal_count = len(commercial)
            intelligence.source_count = len(sources)
            intelligence.competitor_count = len(sources)
            intelligence.activity_score = activity_score
            intelligence.value_score = value_score
            intelligence.fit_score = fit_score
            intelligence.customer_type = "B2B" if is_b2b else "B2C"
            intelligence.quantity_band = self._quantity_band(explicit_quantity)
            intelligence.purchase_horizon = horizons[0] if horizons else None
            intelligence.product_interests_json = self._ranked(product_counts)
            intelligence.top_intents_json = self._ranked(intent_counts)
            intelligence.export_eligibility = (
                ExportEligibility.FIRST_PARTY_ELIGIBLE
                if contact.phone and contact.qualification_updated_at is not None
                else ExportEligibility.NOT_EXPORTABLE
            )
            intelligence.first_seen_at = first_seen
            intelligence.last_seen_at = last_seen
            await session.flush()

            segments = list(
                await session.scalars(
                    select(AudienceSegment).where(AudienceSegment.active.is_(True))
                )
            )
            reactivated = bool(
                len(dates) >= 2 and dates[-1] - dates[-2] >= timedelta(days=30)
            )
            facts = {
                "hot": max_score >= self.hot_threshold,
                "recency_days": recency_days,
                "products": set(product_counts),
                "intents": set(intent_counts),
                "sources": len(sources),
                "customer_type": intelligence.customer_type,
                "quantity": explicit_quantity,
                "value": value_score,
                "reactivated": reactivated,
            }
            for segment in segments:
                active, evidence, expires_at = self._evaluate(
                    segment.criteria_json, facts, last_seen
                )
                membership = await session.scalar(
                    select(AudienceMembership).where(
                        AudienceMembership.segment_id == segment.id,
                        AudienceMembership.contact_id == contact_id,
                    )
                )
                if membership is None:
                    membership = AudienceMembership(
                        segment_id=segment.id,
                        contact_id=contact_id,
                    )
                    session.add(membership)
                membership.active = active
                membership.confidence = min(98, max(50, value_score if active else 50))
                membership.evidence_json = evidence
                membership.expires_at = expires_at
                membership.evaluated_at = now
            await session.commit()
            return intelligence

    @staticmethod
    def _evaluate(criteria: dict, facts: dict, last_seen: datetime):
        evidence: list[str] = []
        active = True
        expires_at = None
        if criteria.get("hot"):
            active &= bool(facts["hot"])
            evidence.append("HOT-порог достигнут")
        if days := criteria.get("days"):
            active &= int(facts["recency_days"]) < int(days)
            expires_at = last_seen + timedelta(days=int(days))
            evidence.append(f"активность за {days} дн.")
        if product := criteria.get("product"):
            active &= product in facts["products"]
            evidence.append(f"товарный интерес: {product}")
        if intent := criteria.get("intent"):
            active &= intent in facts["intents"]
            evidence.append(f"намерение: {intent}")
        if sources := criteria.get("sources"):
            active &= int(facts["sources"]) >= int(sources)
            evidence.append(f"источников: {facts['sources']}")
        if customer_type := criteria.get("customer_type"):
            active &= facts["customer_type"] == customer_type
            evidence.append(f"тип: {customer_type}")
        if quantity := criteria.get("quantity"):
            active &= int(facts["quantity"]) >= int(quantity)
            evidence.append(f"количество: {facts['quantity']}")
        if min_value := criteria.get("min_value"):
            active &= int(facts["value"]) >= int(min_value)
            evidence.append(f"value score: {facts['value']}")
        if criteria.get("reactivated"):
            active &= bool(facts["reactivated"])
            evidence.append("возвращение после паузы 30+ дней")
        return active, evidence if active else [], expires_at

    @staticmethod
    def _ranked(counter: Counter) -> list[dict[str, object]]:
        total = sum(counter.values()) or 1
        return [
            {"value": value, "count": count, "confidence": round(count / total * 100)}
            for value, count in counter.most_common(8)
        ]

    @staticmethod
    def _quantity_band(value: int) -> str | None:
        if value >= 50:
            return "50_PLUS"
        if value >= 20:
            return "20_PLUS"
        if value > 0:
            return "EXPLICIT"
        return None

    @staticmethod
    def _extract_explicit_quantities(text: str) -> list[int]:
        """Return quantities with an explicit unit, never bare price-like numbers."""
        unit_pattern = (
            r"шт(?:\.|ук(?:а|и|ов)?)?|dona|дона|та|персон|киши|kishi|kishilik|кишилик|"
            r"стул(?:а|ов|ья|ьев)?|крес(?:ло|ла|ел)|стол(?:а|ов)?|комплект(?:а|ов)?"
        )
        return [
            int(match.group(1))
            for match in re.finditer(rf"\b(\d{{1,4}})\s*(?:{unit_pattern})\b", text)
        ]

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
