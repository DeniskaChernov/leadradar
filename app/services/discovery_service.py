from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse
from xml.etree import ElementTree

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import normalize_instagram_handle
from app.db.models import MarketCandidate, MarketCandidateDiff, Vertical

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 2_000

FIELD_ALIASES = {
    "name": "display_name",
    "company": "display_name",
    "company_name": "display_name",
    "название": "display_name",
    "компания": "display_name",
    "instagram": "instagram_handle",
    "instagram_handle": "instagram_handle",
    "username": "instagram_handle",
    "website": "website_url",
    "site": "website_url",
    "сайт": "website_url",
    "url": "source_url",
    "source_url": "source_url",
    "source": "source",
    "источник": "source",
    "location": "location",
    "city": "location",
    "город": "location",
    "category": "category",
    "категория": "category",
    "role": "category",
    "vertical": "vertical",
    "вертикаль": "vertical",
    "tier": "tier",
    "priority": "tier",
    "confidence": "confidence",
    "price": "price",
    "цена": "price",
    "stock": "stock",
    "наличие": "stock",
    "notes": "rationale",
    "description": "rationale",
    "описание": "rationale",
}


@dataclass(frozen=True)
class DiscoveryImportResult:
    total_rows: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    diffs_created: int = 0


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalized_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def _website_identity(value: str) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    return host


def _safe_url(value: str) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(candidate)
    return candidate if parsed.scheme in {"http", "https"} and parsed.hostname else ""


def candidate_identity(row: dict[str, str]) -> str:
    handle = normalize_instagram_handle(row.get("instagram_handle", ""))
    if handle:
        return f"instagram:{handle}"
    website = _website_identity(row.get("website_url", ""))
    if website:
        return f"website:{website}"
    name = _normalized_name(row.get("display_name", ""))
    return f"name:{name}" if name else ""


def _snapshot(row: dict[str, str]) -> dict[str, str]:
    allowed = (
        "display_name",
        "instagram_handle",
        "website_url",
        "source_url",
        "source",
        "location",
        "category",
        "vertical",
        "tier",
        "confidence",
        "price",
        "stock",
        "rationale",
    )
    return {key: _clean(row.get(key, "")) for key in allowed if _clean(row.get(key, ""))}


def _fingerprint(snapshot: dict[str, str]) -> str:
    body = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _normalize_row(raw: dict[str, object], *, default_source: str) -> dict[str, str]:
    row: dict[str, str] = {}
    for key, value in raw.items():
        normalized_key = re.sub(r"[^\w]+", "_", _clean(key).casefold()).strip("_")
        target = FIELD_ALIASES.get(normalized_key)
        if target and _clean(value):
            row[target] = _clean(value)
    row.setdefault("source", default_source)
    if row.get("instagram_handle"):
        row["instagram_handle"] = normalize_instagram_handle(row["instagram_handle"])
    for field in ("website_url", "source_url"):
        if row.get(field):
            row[field] = _safe_url(row[field])
    row["category"] = row.get("category", "DIRECT").upper()[:64]
    vertical = row.get("vertical", "").casefold()
    row["vertical"] = (
        Vertical.ARTIFICIAL_RATTAN.value
        if vertical in {"artificial_rattan", "rattan", "rotang", "ротанг", "искусственный ротанг"}
        else Vertical.FURNITURE.value
    )
    tier = row.get("tier", "B").upper()
    row["tier"] = tier if tier in {"A", "B", "C"} else "B"
    try:
        confidence = max(0, min(100, int(float(row.get("confidence", "50")))))
    except ValueError:
        confidence = 50
    row["confidence"] = str(confidence)
    return row


def _csv_rows(payload: bytes) -> list[dict[str, object]]:
    text = payload.decode("utf-8-sig")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [dict(row) for row in csv.DictReader(io.StringIO(text), dialect=dialect)]


def _xlsx_rows(payload: bytes) -> list[dict[str, object]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root]
        sheets = sorted(
            name
            for name in workbook.namelist()
            if PurePosixPath(name).match("xl/worksheets/sheet*.xml")
        )
        if not sheets:
            return []
        root = ElementTree.fromstring(workbook.read(sheets[0]))
        rows: list[list[str]] = []
        for row_node in root.iterfind(".//{*}row"):
            values: list[str] = []
            for cell in row_node.findall("{*}c"):
                ref = cell.attrib.get("r", "A1")
                column = 0
                for char in re.match(r"[A-Z]+", ref).group(0):  # type: ignore[union-attr]
                    column = column * 26 + ord(char) - 64
                while len(values) < column:
                    values.append("")
                value_node = cell.find("{*}v")
                value = value_node.text if value_node is not None and value_node.text else ""
                if cell.attrib.get("t") == "s" and value:
                    value = shared[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(cell.itertext())
                values[column - 1] = value
            rows.append(values)
    if not rows:
        return []
    headers = [_clean(value) for value in rows[0]]
    return [dict(zip(headers, values, strict=False)) for values in rows[1:]]


def parse_discovery_file(filename: str, payload: bytes) -> list[dict[str, str]]:
    if not payload:
        raise ValueError("Файл пуст")
    if len(payload) > MAX_IMPORT_BYTES:
        raise ValueError("Файл больше 5 МБ")
    suffix = PurePosixPath(filename.casefold()).suffix
    if suffix not in {".csv", ".xlsx"}:
        raise ValueError("Поддерживаются только файлы CSV и XLSX")
    try:
        raw_rows = _xlsx_rows(payload) if suffix == ".xlsx" else _csv_rows(payload)
    except (UnicodeDecodeError, csv.Error, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError("Не удалось прочитать CSV/XLSX файл") from exc
    if len(raw_rows) > MAX_IMPORT_ROWS:
        raise ValueError(f"За один раз можно импортировать не более {MAX_IMPORT_ROWS} строк")
    source = "XLSX_IMPORT" if suffix == ".xlsx" else "CSV_IMPORT"
    return [_normalize_row(row, default_source=source) for row in raw_rows]


class DiscoveryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        self._import_lock = asyncio.Lock()

    async def dashboard(self) -> dict[str, object]:
        async with self.session_factory() as session:
            candidates = (
                await session.scalars(
                    select(MarketCandidate)
                    .where(MarketCandidate.status != "PROMOTED")
                    .order_by(
                        MarketCandidate.status,
                        MarketCandidate.tier,
                        desc(MarketCandidate.confidence),
                        MarketCandidate.display_name,
                    )
                )
            ).all()
            changes = (
                await session.execute(
                    select(MarketCandidateDiff, MarketCandidate)
                    .join(MarketCandidate, MarketCandidate.id == MarketCandidateDiff.candidate_id)
                    .where(MarketCandidateDiff.acknowledged_at.is_(None))
                    .order_by(desc(MarketCandidateDiff.created_at))
                    .limit(50)
                )
            ).all()
            status_rows = await session.execute(
                select(MarketCandidate.status, func.count(MarketCandidate.id))
                .where(MarketCandidate.status != "PROMOTED")
                .group_by(MarketCandidate.status)
            )
            status_counts = {status: int(count) for status, count in status_rows}
            return {
                "candidates": candidates,
                "changes": changes,
                "counts": {
                    "discovered": int(status_counts.get("DISCOVERED", 0)),
                    "reviewed": int(status_counts.get("REVIEWED", 0)),
                    "rejected": int(status_counts.get("REJECTED", 0)),
                    "changes": len(changes),
                },
            }

    async def import_file(self, filename: str, payload: bytes) -> DiscoveryImportResult:
        # A database unique index is the final guard. This lock also makes concurrent imports in
        # the normal single-process local deployment return clean counters instead of a conflict.
        async with self._import_lock:
            return await self._import_file_unlocked(filename, payload)

    async def _import_file_unlocked(
        self, filename: str, payload: bytes
    ) -> DiscoveryImportResult:
        rows = parse_discovery_file(filename, payload)
        counters = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "diffs_created": 0}
        async with self.session_factory() as session:
            for row in rows:
                if not row.get("display_name"):
                    counters["skipped"] += 1
                    continue
                identity = candidate_identity(row)
                if not identity:
                    counters["skipped"] += 1
                    continue
                candidate = await self._find_candidate(session, row, identity)
                snapshot = _snapshot(row)
                fingerprint = _fingerprint(snapshot)
                now = datetime.now(UTC)
                if candidate is None:
                    candidate = MarketCandidate(
                        display_name=row["display_name"],
                        canonical_key=identity,
                        vertical=Vertical(row["vertical"]),
                        instagram_handle=row.get("instagram_handle") or None,
                        website_url=row.get("website_url") or None,
                        source_url=row.get("source_url") or None,
                        source=row["source"][:64],
                        location=row.get("location") or None,
                        category=row["category"],
                        tier=row["tier"],
                        confidence=int(row["confidence"]),
                        rationale=row.get("rationale") or None,
                        snapshot=snapshot,
                        snapshot_fingerprint=fingerprint,
                        last_seen_at=now,
                    )
                    session.add(candidate)
                    await session.flush()
                    session.add(self._diff(candidate, None, snapshot, fingerprint, "NEW"))
                    counters["created"] += 1
                    counters["diffs_created"] += 1
                    continue
                candidate.last_seen_at = now
                candidate.canonical_key = candidate.canonical_key or identity
                if candidate.snapshot_fingerprint == fingerprint:
                    counters["unchanged"] += 1
                    continue
                before = candidate.snapshot
                changed = sorted(
                    key for key in set(before or {}) | set(snapshot) if (before or {}).get(key) != snapshot.get(key)
                )
                diff_type = self._diff_type(changed)
                session.add(self._diff(candidate, before, snapshot, fingerprint, diff_type, changed))
                self._apply_snapshot(candidate, row, snapshot, fingerprint)
                counters["updated"] += 1
                counters["diffs_created"] += 1
            await session.commit()
        return DiscoveryImportResult(total_rows=len(rows), **counters)

    @staticmethod
    async def _find_candidate(
        session: AsyncSession, row: dict[str, str], identity: str
    ) -> MarketCandidate | None:
        checks = [MarketCandidate.canonical_key == identity]
        if row.get("instagram_handle"):
            checks.append(MarketCandidate.instagram_handle == row["instagram_handle"])
        if row.get("website_url"):
            checks.append(MarketCandidate.website_url == row["website_url"])
        checks.append(MarketCandidate.display_name == row["display_name"])
        return await session.scalar(select(MarketCandidate).where(or_(*checks)).limit(1))

    @staticmethod
    def _apply_snapshot(
        candidate: MarketCandidate,
        row: dict[str, str],
        snapshot: dict[str, str],
        fingerprint: str,
    ) -> None:
        candidate.display_name = row["display_name"]
        candidate.instagram_handle = row.get("instagram_handle") or candidate.instagram_handle
        candidate.website_url = row.get("website_url") or candidate.website_url
        candidate.source_url = row.get("source_url") or candidate.source_url
        candidate.source = row["source"][:64]
        candidate.location = row.get("location") or candidate.location
        candidate.category = row["category"]
        candidate.vertical = Vertical(row["vertical"])
        candidate.tier = row["tier"]
        candidate.confidence = int(row["confidence"])
        candidate.rationale = row.get("rationale") or candidate.rationale
        candidate.snapshot = snapshot
        candidate.snapshot_fingerprint = fingerprint

    @staticmethod
    def _diff_type(changed: list[str]) -> str:
        if "price" in changed:
            return "PRICE_CHANGED"
        if "stock" in changed:
            return "STOCK_CHANGED"
        if "category" in changed:
            return "ROLE_CHANGED"
        return "UPDATED"

    @staticmethod
    def _diff(
        candidate: MarketCandidate,
        before: dict[str, str] | None,
        after: dict[str, str],
        fingerprint: str,
        diff_type: str,
        changed: list[str] | None = None,
    ) -> MarketCandidateDiff:
        return MarketCandidateDiff(
            candidate_id=candidate.id,
            diff_type=diff_type,
            changed_fields=changed or list(after),
            before_snapshot=before,
            after_snapshot=after,
            snapshot_fingerprint=fingerprint,
        )

    async def set_status(self, candidate_id: int, status: str) -> MarketCandidate:
        normalized = status.strip().upper()
        if normalized not in {"DISCOVERED", "REVIEWED", "REJECTED"}:
            raise ValueError("Неизвестный статус кандидата")
        async with self.session_factory() as session:
            candidate = await session.get(MarketCandidate, candidate_id)
            if candidate is None:
                raise ValueError("Кандидат не найден")
            if candidate.status == "PROMOTED":
                raise ValueError("Компания уже добавлена в радар")
            candidate.status = normalized
            await session.commit()
            return candidate

    async def acknowledge_diff(self, diff_id: int) -> MarketCandidateDiff:
        async with self.session_factory() as session:
            diff = await session.get(MarketCandidateDiff, diff_id)
            if diff is None:
                raise ValueError("Изменение не найдено")
            diff.acknowledged_at = diff.acknowledged_at or datetime.now(UTC)
            await session.commit()
            return diff
