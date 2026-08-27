"""
place_opening_service.py — Phase 10 Google Future Openings & Place Resolution

Detects future venue opening signals (restaurants, cafes, hotels, showrooms),
manages place resolution, and provides a manager review queue.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OpeningSignal


class PlaceOpeningService:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        self.session_factory = session_factory

    @staticmethod
    def detect_opening_signals(
        comment_text: str, caption_text: str = ""
    ) -> dict[str, Any] | None:
        """Rule-based extractor for venue openings in commercial comments/captions."""
        combined = f"{(comment_text or '')} {(caption_text or '')}".lower()

        opening_markers = (
            "открываем",
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
        timeline = "В БЛИЖАЙШЕЕ ВРЕМЯ"
        if "следующ" in combined or "kelasi" in combined:
            timeline = "НА СЛЕДУЮЩЕЙ НЕДЕЛЕ"
        elif "скоро" in combined or "tezda" in combined:
            timeline = "СКОРО"
        elif "месяц" in combined or "shu oy" in combined:
            timeline = "В ЭТОМ МЕСЯЦЕ"

        # Confidence calculation
        confidence = 65
        if place_type != "OTHER":
            confidence += 15
        if any(w in combined for w in ("открываем", "открытие", "ochilish")):
            confidence += 10

        place_name = f"Новый объект ({place_type})"
        # Simple venue name extraction if available
        name_match = re.search(r'(?:ресторан|кафе|отель|шоурум)\s+["«]?([^"»\n,\.]{3,30})["»]?', combined)
        if name_match:
            place_name = f"{place_type.capitalize()} «{name_match.group(1).strip().title()}»"

        return {
            "place_name": place_name,
            "place_type": place_type,
            "city": "Tashkent",
            "opening_timeline": timeline,
            "confidence": min(95, confidence),
        }

    async def store_opening_signal(
        self,
        place_name: str,
        place_type: str,
        city: str = "Tashkent",
        address: str | None = None,
        opening_timeline: str | None = None,
        contact_id: int | None = None,
        lead_id: int | None = None,
        confidence: int = 70,
        source_type: str = "INSTAGRAM_PUBLIC_SIGNAL",
    ) -> OpeningSignal:
        async with self.session_factory() as session:
            # Check for existing duplicate signal for this contact
            if contact_id:
                existing = await session.scalar(
                    select(OpeningSignal).where(
                        OpeningSignal.contact_id == contact_id,
                        OpeningSignal.place_name == place_name,
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
            await session.commit()
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
