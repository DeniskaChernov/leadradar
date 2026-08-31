from __future__ import annotations

import asyncio
import io
import zipfile

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import MarketCandidate, MarketCandidateDiff
from app.services.discovery_service import DiscoveryService, parse_discovery_file
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService


class FakeMonitor:
    provider = None


def _xlsx_payload() -> bytes:
    worksheet = """<?xml version="1.0" encoding="UTF-8"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
      <row r="1"><c r="A1" t="inlineStr"><is><t>company</t></is></c><c r="B1" t="inlineStr"><is><t>instagram</t></is></c></row>
      <row r="2"><c r="A2" t="inlineStr"><is><t>Rattan House</t></is></c><c r="B2" t="inlineStr"><is><t>@rattan.house</t></is></c></row>
    </sheetData></worksheet>"""
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as workbook:
        workbook.writestr("xl/worksheets/sheet1.xml", worksheet)
    return target.getvalue()


def test_csv_and_xlsx_parser_support_expected_columns():
    csv_rows = parse_discovery_file(
        "companies.csv",
        "Компания;Instagram;Цена;Вертикаль\nRattan House;@rattan.house;120000;ротанг\n".encode(),
    )
    xlsx_rows = parse_discovery_file("companies.xlsx", _xlsx_payload())

    assert csv_rows[0]["display_name"] == "Rattan House"
    assert csv_rows[0]["instagram_handle"] == "rattan.house"
    assert csv_rows[0]["price"] == "120000"
    assert csv_rows[0]["vertical"] == "ARTIFICIAL_RATTAN"
    assert xlsx_rows[0]["display_name"] == "Rattan House"
    assert xlsx_rows[0]["instagram_handle"] == "rattan.house"


async def test_import_is_idempotent_and_records_only_real_changes(session_factory):
    service = DiscoveryService(session_factory)
    first = b"company,instagram,price,stock\nRattan House,rattan.house,120000,in stock\n"
    changed = b"company,instagram,price,stock\nRattan House,rattan.house,135000,in stock\n"

    created = await service.import_file("companies.csv", first)
    repeated = await service.import_file("companies.csv", first)
    updated = await service.import_file("companies.csv", changed)

    assert created.created == 1
    assert created.diffs_created == 1
    assert repeated.unchanged == 1
    assert repeated.diffs_created == 0
    assert updated.updated == 1
    assert updated.diffs_created == 1

    async with session_factory() as session:
        assert int(await session.scalar(select(func.count(MarketCandidate.id))) or 0) == 1
        diffs = (
            await session.scalars(select(MarketCandidateDiff).order_by(MarketCandidateDiff.id))
        ).all()
    assert [diff.diff_type for diff in diffs] == ["NEW", "PRICE_CHANGED"]
    assert diffs[-1].changed_fields == ["price"]


async def test_import_matches_same_company_by_handle_even_if_name_changes(session_factory):
    service = DiscoveryService(session_factory)
    await service.import_file("first.csv", b"name,instagram\nOld Name,same.handle\n")
    result = await service.import_file("second.csv", b"name,instagram\nNew Name,same.handle\n")

    assert result.updated == 1
    async with session_factory() as session:
        candidates = (await session.scalars(select(MarketCandidate))).all()
    assert len(candidates) == 1
    assert candidates[0].display_name == "New Name"


async def test_concurrent_repeated_import_creates_one_candidate(session_factory):
    service = DiscoveryService(session_factory)
    payload = b"company,instagram\nRattan House,rattan.house\n"

    results = await asyncio.gather(
        service.import_file("one.csv", payload),
        service.import_file("two.csv", payload),
    )

    assert sum(result.created for result in results) == 1
    assert sum(result.unchanged for result in results) == 1
    async with session_factory() as session:
        assert int(await session.scalar(select(func.count(MarketCandidate.id))) or 0) == 1


async def test_discovery_page_import_and_review_workflow(session_factory):
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay", web_manager_id=1001)
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        imported = await client.post(
            "/api/discovery/import?filename=companies.csv",
            content=b"company,instagram,city\nRattan House,rattan.house,Tashkent\n",
            headers={"content-type": "application/octet-stream"},
        )
        page = await client.get("/discovery")
        async with session_factory() as session:
            candidate = await session.scalar(select(MarketCandidate))
            assert candidate is not None
            candidate_id = candidate.id
        reviewed = await client.post(
            f"/api/discovery/candidates/{candidate_id}/status", json={"status": "REVIEWED"}
        )
        promoted = await client.post(
            f"/api/market-candidates/{candidate_id}/promote",
            json={"handle": "rattan.house", "active": False},
        )

    assert imported.status_code == 200
    assert imported.json()["created"] == 1
    assert page.status_code == 200
    assert "Rattan House" in page.text
    assert "Повторная загрузка не создаёт дубли" in page.text
    assert reviewed.json()["status"] == "REVIEWED"
    assert promoted.status_code == 200
