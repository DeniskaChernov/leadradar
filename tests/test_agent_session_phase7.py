from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.services.agent_session_service import AgentSessionService
from app.services.allowed_audience_registry import AllowedAudienceRegistry
from app.services.audience_membership_resolver import AudienceMembershipResolver
from app.services.lead_workflow_service import LeadWorkflowService
from app.services.mcp_gateway_service import LeadRadarMCPGateway
from app.services.mcp_read_tool_service import MCPReadToolService
from app.services.monitor_controller import MonitorController
from app.web.app import build_web_app
from app.web.queries import WebQueryService
from tests.test_lead_workflow import create_lead


class FakeMonitor:
    async def start(self):
        return None

    async def stop(self):
        return None

    def status(self):
        return {"running": False}


@pytest.mark.asyncio
async def test_mcp_read_tool_lead_search_returns_evidence(session_factory):
    lead_id = await create_lead(session_factory)
    read_service = MCPReadToolService(session_factory, hot_threshold=70)
    gateway = LeadRadarMCPGateway(read_service)

    result = await gateway.execute_tool_async("lead.search", {"query": "user-1"})

    assert result.success is True
    assert result.output["count"] >= 1
    assert any(item["lead_id"] == lead_id for item in result.output["leads"])


@pytest.mark.asyncio
async def test_mcp_read_tool_lead_explain_score_includes_memberships(session_factory):
    lead_id = await create_lead(session_factory)
    read_service = MCPReadToolService(session_factory, hot_threshold=70)

    output = await read_service.lead_explain_score(lead_id)

    assert output["lead_id"] == lead_id
    assert "score" in output
    assert isinstance(output["evidence_ids"], list)
    assert isinstance(output["audience_memberships"], list)


@pytest.mark.asyncio
async def test_audience_dna_rejects_non_active_slug(session_factory):
    read_service = MCPReadToolService(session_factory, hot_threshold=70)

    output = await read_service.audience_dna("not-a-real-segment")

    assert output["error"] == "AUDIENCE_NOT_ALLOWED"
    assert output["allowed_slugs"]


def test_allowed_audience_registry_lists_active_only():
    slugs = {item.slug for item in AllowedAudienceRegistry.list_active()}
    assert slugs
    assert AllowedAudienceRegistry.is_allowed(next(iter(slugs)))
    assert not AllowedAudienceRegistry.is_allowed("definitely-not-active")


@pytest.mark.asyncio
async def test_audience_membership_resolver_returns_snapshot(session_factory):
    lead_id = await create_lead(session_factory)
    read_service = MCPReadToolService(session_factory, hot_threshold=70)
    explain = await read_service.lead_explain_score(lead_id)
    resolver = AudienceMembershipResolver(session_factory)

    snapshot = await resolver.resolve_contact(explain["contact_id"])

    assert snapshot is not None
    assert snapshot.contact_id == explain["contact_id"]
    assert isinstance(snapshot.memberships, tuple)


@pytest.mark.asyncio
async def test_agent_session_service_is_grounded_without_fake_catalog(session_factory):
    await create_lead(session_factory)
    service = AgentSessionService(session_factory, hot_threshold=70)

    result = await service.query("Что предложить?")

    assert result.grounded is True
    assert result.tool_calls[0].result.success is True
    assert result.synthesis_mode == "offline_deterministic"
    assert "SKU-DINING-SET-6P" not in result.answer
    assert "10%" not in result.answer
    assert "24-hour" not in result.answer.lower()
    assert "каталог" in result.answer.lower()


@pytest.mark.asyncio
async def test_agent_query_endpoint_returns_grounded_payload(session_factory):
    await create_lead(session_factory)
    settings = Settings(_env_file=None, web_enabled=True, instagram_provider="replay")
    app = build_web_app(
        settings,
        WebQueryService(session_factory, hot_threshold=70),
        LeadWorkflowService(session_factory, hot_threshold=70),
        MonitorController(FakeMonitor()),  # type: ignore[arg-type]
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/agent/query", json={"query": "Покажи лиды"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["grounded"] is True
    assert payload["tool_calls"][0]["success"] is True
    assert payload["synthesis_mode"] == "offline_deterministic"
    assert payload["tool_calls"][0]["tool_name"] == "lead.search"
    assert "SKU-DINING-SET-6P" not in payload["answer"]


def test_mcp_gateway_write_tool_still_requires_approval():
    result = LeadRadarMCPGateway.execute_tool(
        "meta.create_campaign_draft",
        {"recipe_type": "NARROW", "budget_usd": 100},
        approval_granted=False,
    )
    assert result.success is False
    assert "requires explicit human approval" in result.output["error"]


@pytest.mark.asyncio
async def test_mcp_gateway_write_tool_stays_not_connected_even_with_approval(session_factory):
    gateway = LeadRadarMCPGateway.from_session_factory(session_factory, hot_threshold=70)
    result = await gateway.execute_tool_async(
        "meta.create_campaign_draft",
        {"recipe_type": "NARROW", "budget_usd": 100},
        approval_granted=True,
    )
    assert result.success is False
    assert result.output["error"] == "NOT_CONNECTED"
