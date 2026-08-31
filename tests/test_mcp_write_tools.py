"""Tests for approval-gated MCP write tools."""

from __future__ import annotations

import pytest

from app.services.mcp_gateway_service import LeadRadarMCPGateway
from tests.test_lead_workflow import create_lead


@pytest.mark.asyncio
async def test_crm_assign_lead_requires_approval(session_factory):
    gateway = LeadRadarMCPGateway.from_session_factory(session_factory, hot_threshold=70)

    result = await gateway.execute_tool_async(
        "crm.assign_lead",
        {"lead_id": 1, "manager_id": 42},
        approval_granted=False,
    )

    assert result.success is False
    assert "requires explicit human approval" in result.output["error"]


@pytest.mark.asyncio
async def test_crm_assign_lead_with_approval_assigns_manager(session_factory):
    lead_id = await create_lead(session_factory)
    gateway = LeadRadarMCPGateway.from_session_factory(session_factory, hot_threshold=70)

    result = await gateway.execute_tool_async(
        "crm.assign_lead",
        {"lead_id": lead_id, "manager_id": 4242},
        approval_granted=True,
    )

    assert result.success is True
    assert result.output["assigned_manager_id"] == 4242
    assert result.output["status"] == "TAKEN"


@pytest.mark.asyncio
async def test_meta_write_tool_stays_not_connected_with_approval(session_factory):
    gateway = LeadRadarMCPGateway.from_session_factory(session_factory, hot_threshold=70)

    result = await gateway.execute_tool_async(
        "meta.create_campaign_draft",
        {"recipe_type": "NARROW", "budget_usd": 100},
        approval_granted=True,
    )

    assert result.success is False
    assert result.output["error"] == "NOT_CONNECTED"
