"""Импорт конкурентов из CSV/XLSX в таблицу competitors (idempotent, на паузе)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import normalize_instagram_handle
from app.db.models import Competitor, Vertical
from app.services.discovery_service import MAX_IMPORT_BYTES, parse_discovery_file


@dataclass(frozen=True, slots=True)
class CompetitorImportResult:
    total_rows: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0


class CompetitorImportService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def import_file(self, filename: str, content: bytes) -> CompetitorImportResult:
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError("Файл слишком большой (максимум 5 МБ)")
        rows = parse_discovery_file(filename, content)
        created = 0
        updated = 0
        skipped = 0
        async with self.session_factory() as session:
            for row in rows:
                handle = normalize_instagram_handle(row.get("instagram_handle") or "")
                if not handle:
                    skipped += 1
                    continue
                tier = (row.get("tier") or "B").strip().upper()
                if tier not in {"A", "B", "C"}:
                    tier = "B"
                vertical_raw = (row.get("vertical") or Vertical.FURNITURE.value).strip().upper()
                try:
                    vertical = Vertical(vertical_raw)
                except ValueError:
                    vertical = Vertical.FURNITURE
                category = (row.get("category") or "DIRECT").strip().upper() or "DIRECT"
                display_name = (row.get("display_name") or handle).strip()
                notes = (row.get("rationale") or row.get("notes") or "").strip() or None
                competitor = await session.scalar(
                    select(Competitor).where(Competitor.normalized_handle == handle)
                )
                if competitor is None:
                    session.add(
                        Competitor(
                            handle=handle,
                            normalized_handle=handle,
                            display_name=display_name,
                            category=category,
                            tier=tier,
                            poll_interval_seconds={"A": 180, "B": 600, "C": 1800}[tier],
                            notes=notes,
                            active=False,
                            vertical=vertical,
                        )
                    )
                    created += 1
                else:
                    if display_name and not competitor.display_name:
                        competitor.display_name = display_name
                    if notes and not competitor.notes:
                        competitor.notes = notes
                    updated += 1
            await session.commit()
        return CompetitorImportResult(
            total_rows=len(rows),
            created=created,
            updated=updated,
            skipped=skipped,
        )
