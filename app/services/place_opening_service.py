"""Extract venue openings from saved public comments for manager review.

This service does not call Google Places or resolve venue addresses.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Comment, Contact, Lead, OpeningSignal
from app.services.signal_recency import (
    fresh_signal_clause,
    is_signal_within_window,
    signal_observed_at,
)


class PlaceOpeningService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

    @staticmethod
    def detect_opening_signals(
        comment_text: str, caption_text: str = ""
    ) -> dict[str, Any] | None:
        """Extract only the author's statement, never attribute a post to a commenter.

        caption_text is retained for callers but is not evidence about the commenter.
        All matches remain unverified until a manager reviews their source lead.
        """
        combined = (comment_text or "").lower()
        if re.search(r"\b(?:не\s+открыва|поздравл|когда\s+откры|открытие[^.!?\n]{0,80}отмен)", combined):
            return None

        opening_markers = (
            "открываем",
            "открываю",
            "открытие",
            "скоро открытие",
            "новое кафе",
            "новый ресторан",
            "новый отель",
            "новый шоурум",
            "ochilishi",
            "ochildik",
            "yangi kafe",
            "yangi restoran",
            "очилиши",
            "янги кафе",
            "янги ресторан",
            "для проекта отеля",
            "для нового объекта",
            "kafe och",
            "restoran och",
            "кафе очил",
            "ресторан очил",
        )
        if not any(marker in combined for marker in opening_markers):
            return None

        # Determine place type
        place_type = "OTHER"
        if any(w in combined for w in ("ресторан", "restoran", "ресторана")):
            place_type = "RESTAURANT"
        elif any(w in combined for w in ("кафе", "kafe", "кофейня")):
            place_type = "CAFE"
        elif any(w in combined for w in ("отель", "гостиниц", "hotel", "mehmonxona")):
            place_type = "HOTEL"
        elif any(w in combined for w in ("шоурум", "showroom", "магазин")):
            place_type = "SHOWROOM"
        elif any(w in combined for w in ("офис", "office")):
            place_type = "OFFICE"

        # Determine timeline
        timeline = None
        if re.search(r"следующ\w*\s+месяц|kelasi\s+oy|кейинги\s+ой", combined):
            timeline = "В СЛЕДУЮЩЕМ МЕСЯЦЕ"
        elif re.search(r"следующ\w*\s+недел|kelasi\s+hafta|кейинги\s+ҳафта", combined):
            timeline = "НА СЛЕДУЮЩЕЙ НЕДЕЛЕ"
        elif re.search(r"этом\s+месяц|shu\s+oy|шу\s+ой", combined):
            timeline = "В ЭТОМ МЕСЯЦЕ"
        elif "скоро" in combined or "tezda" in combined:
            timeline = "СКОРО"

        if place_type == "OTHER" and "для нового объекта" not in combined:
            return None

        # Confidence calculation
        confidence = 65
        if place_type != "OTHER":
            confidence += 15
        if any(w in combined for w in ("открываем", "открытие", "ochilish")):
            confidence += 10

        place_name = f"Новый объект ({place_type})"
        # Require a quoted name; "кафе в Бухаре" is a location, not a venue name.
        name_match = re.search(
            r'(?:ресторан\w*|кафе|отел\w*|шоурум\w*|restoran|kafe|hotel)\s+["«]([^"»\n]{2,80})["»]',
            comment_text or "", re.IGNORECASE,
        )
        if name_match:
            place_name = f"{place_type.capitalize()} «{name_match.group(1).strip()}»"

        cities = {
            "Tashkent": r"\b(?:ташкент\w*|tashkent\w*|toshkent\w*|тошкент\w*)\b",
            "Samarkand": r"\b(?:самарканд\w*|samarqand\w*|samarkand\w*|самарқанд\w*)\b",
            "Bukhara": r"\b(?:бухар\w*|buxoro\w*|bukhara\w*)\b",
            "Namangan": r"\b(?:наманган\w*|namangan\w*)\b",
            "Andijan": r"\b(?:андижан\w*|andijon\w*|andijan\w*|андижон\w*)\b",
            "Fergana": r"\b(?:ферган\w*|farg['’ʻ‘]?ona\w*)\b",
            "Nukus": r"\b(?:нукус\w*|nukus\w*)\b",
        }
        # Multiple mentioned cities do not establish the venue location.
        found_cities = [city for city, pattern in cities.items() if re.search(pattern, combined)]

        return {
            "place_name": place_name,
            "place_type": place_type,
            "city": found_cities[0] if len(found_cities) == 1 else None,
            "opening_timeline": timeline,
            "confidence": min(95, confidence),
        }

    @classmethod
    async def capture_lead(
        cls, session: AsyncSession, lead: Lead, comment: Comment, *, max_age_days: int = 30
    ) -> bool:
        """Persist extraction inside the lead transaction, before any notification."""
        if lead.opening_checked_at is not None:
            return False
        data = None
        if is_signal_within_window(
            signal_observed_at(
                created_at_platform=comment.created_at_platform,
                discovered_at=comment.discovered_at,
            ), max_age_days=max_age_days,
        ):
            data = cls.detect_opening_signals(comment.text)
        created = False
        if data is not None:
            if data["place_name"].startswith("Новый объект"):
                data["place_name"] += f" · сигнал #{lead.id}"
            existing = await session.scalar(select(OpeningSignal.id).where(
                OpeningSignal.contact_id == lead.contact_id,
                OpeningSignal.place_name == data["place_name"],
            ))
            if existing is None:
                try:
                    async with session.begin_nested():
                        session.add(OpeningSignal(
                            **data, contact_id=lead.contact_id, lead_id=lead.id,
                            source_type="INSTAGRAM_PUBLIC_COMMENT", review_status="PENDING_REVIEW",
                        ))
                        await session.flush()
                    created = True
                except IntegrityError:
                    # A concurrent lead for the same named venue may have won.
                    existing = await session.scalar(select(OpeningSignal.id).where(
                        OpeningSignal.contact_id == lead.contact_id,
                        OpeningSignal.place_name == data["place_name"],
                    ))
                    if existing is None:
                        raise
        await session.execute(update(Lead).where(Lead.id == lead.id).values(
            opening_checked_at=datetime.now(UTC), updated_at=Lead.updated_at,
        ))
        return created

    async def backfill_saved_leads(self, *, max_age_days: int = 30, batch_size: int = 200) -> dict[str, int]:
        """Recover unchecked committed signals in bounded, repeatable DB-only batches."""
        checked = created = 0
        last_id = 0
        while True:
            async with self.session_factory() as session:
                rows = (await session.execute(
                    select(Lead, Comment).join(Comment, Comment.id == Lead.comment_id).where(
                        Lead.id > last_id, Lead.opening_checked_at.is_(None),
                        fresh_signal_clause(max_age_days=max_age_days),
                    ).order_by(Lead.id).limit(max(1, min(batch_size, 1000)))
                )).all()
                if not rows:
                    break
                for lead, comment in rows:
                    created += await self.capture_lead(session, lead, comment, max_age_days=max_age_days)
                    checked += 1
                    last_id = lead.id
                await session.commit()
        return {"checked": checked, "created": created}

    async def store_opening_signal(
        self,
        place_name: str,
        place_type: str,
        city: str | None = None,
        address: str | None = None,
        opening_timeline: str | None = None,
        contact_id: int | None = None,
        lead_id: int | None = None,
        confidence: int = 70,
        source_type: str = "INSTAGRAM_PUBLIC_SIGNAL",
    ) -> OpeningSignal:
        async with self.session_factory() as session:
            if contact_id is not None and await session.get(Contact, contact_id) is None:
                raise ValueError(f"Contact not found: {contact_id}")
            if lead_id is not None:
                lead = await session.get(Lead, lead_id)
                if lead is None:
                    raise ValueError(f"Lead not found: {lead_id}")
                if contact_id is not None and lead.contact_id != contact_id:
                    raise ValueError("Lead does not belong to the opening-signal contact")
            # Идемпотентность: при contact_id — unique constraint; без него — явный lookup.
            if contact_id is not None:
                existing = await session.scalar(
                    select(OpeningSignal).where(
                        OpeningSignal.contact_id == contact_id,
                        OpeningSignal.place_name == place_name,
                    )
                )
            else:
                existing = await session.scalar(
                    select(OpeningSignal).where(
                        OpeningSignal.contact_id.is_(None),
                        OpeningSignal.place_name == place_name,
                        OpeningSignal.city == city,
                        OpeningSignal.review_status == "PENDING_REVIEW",
                    )
                )
            if existing is not None:
                return existing

            signal = OpeningSignal(
                place_name=place_name,
                place_type=place_type,
                city=city,
                address=address,
                opening_timeline=opening_timeline,
                confidence=confidence,
                source_type=source_type,
                contact_id=contact_id,
                lead_id=lead_id,
                review_status="PENDING_REVIEW",
                created_at=datetime.now(UTC),
            )
            session.add(signal)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                if contact_id is None:
                    existing = await session.scalar(
                        select(OpeningSignal).where(
                            OpeningSignal.contact_id.is_(None),
                            OpeningSignal.place_name == place_name,
                            OpeningSignal.city == city,
                            OpeningSignal.review_status == "PENDING_REVIEW",
                        )
                    )
                else:
                    existing = await session.scalar(
                        select(OpeningSignal).where(
                            OpeningSignal.contact_id == contact_id,
                            OpeningSignal.place_name == place_name,
                        )
                    )
                if existing is None:
                    raise
                return existing
            return signal

    async def review_opening_signal(
        self, opening_id: int, manager_id: int, decision: str
    ) -> OpeningSignal:
        decision_upper = decision.upper()
        if decision_upper not in ("VERIFIED", "REJECTED"):
            raise ValueError(f"Invalid review decision: {decision}. Must be VERIFIED or REJECTED.")

        async with self.session_factory() as session:
            signal = await session.get(OpeningSignal, opening_id)
            if signal is None:
                raise ValueError(f"OpeningSignal not found: {opening_id}")
            if signal.review_status == decision_upper:
                return signal
            if signal.review_status != "PENDING_REVIEW":
                raise ValueError(
                    "Reviewed OpeningSignal cannot be overwritten with another decision"
                )
            signal.review_status = decision_upper
            signal.reviewed_by_manager_id = manager_id
            signal.reviewed_at = datetime.now(UTC)
            await session.commit()
            return signal

    async def get_review_queue(self) -> list[OpeningSignal]:
        async with self.session_factory() as session:
            return list(
                await session.scalars(
                    select(OpeningSignal)
                    .where(OpeningSignal.review_status == "PENDING_REVIEW")
                    .order_by(OpeningSignal.confidence.desc(), OpeningSignal.id.desc())
                )
            )
