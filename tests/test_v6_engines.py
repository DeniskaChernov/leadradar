"""
test_v6_engines.py — Master Phase V6 tests for Competitor Opportunities, Meta Recipes, and MCP Gateway.
"""

from __future__ import annotations

from app.services.competitor_opportunity_service import CompetitorOpportunityEngine
from app.services.mcp_gateway_service import LeadRadarMCPGateway
from app.services.targeting_recipe_service import TargetingRecipeEngine


def test_competitor_scoring_and_opportunities():
    score = CompetitorOpportunityEngine.score_post_content(
        post_id="p-1",
        total_comments=20,
        price_count=5,
        availability_count=2,
        b2b_count=3,
    )
    assert score.commercial_intent_rate == 50.0
    assert score.is_high_converting is True

def test_targeting_recipes_generation():
    recipes = TargetingRecipeEngine.generate_recipes(
        audience_name="Hot Dining Set Buyers",
        top_category="DINING_SET",
    )
    assert len(recipes) == 3
    recipe_types = [r.recipe_type for r in recipes]
    assert "NARROW" in recipe_types
    assert "BALANCED" in recipe_types
    assert "BROAD" in recipe_types
    assert all(recipe.status == "NOT_CONNECTED" for recipe in recipes)
    assert all(not recipe.interest_ids for recipe in recipes)


def test_mcp_gateway_audience_dna_is_audience_namespace():
    tools = LeadRadarMCPGateway.list_tools(namespace="audience")
    assert [tool.name for tool in tools] == ["audience.dna"]


def test_mcp_gateway_read_tool_is_honestly_not_connected_without_service():
    result = LeadRadarMCPGateway.execute_tool(
        "lead.search",
        {"query": "dining set"},
        approval_granted=False,
    )
    assert result.success is False
    assert result.output["error"] == "NOT_CONNECTED"


def test_mcp_gateway_write_tool_requires_approval():
    # Without approval -> fails
    res_no = LeadRadarMCPGateway.execute_tool(
        "meta.create_campaign_draft",
        {"recipe_type": "NARROW", "budget_usd": 100},
        approval_granted=False,
    )
    assert res_no.success is False
    assert "requires explicit human approval" in res_no.output["error"]

    # Approval does not turn a mock into a real integration.
    res_yes = LeadRadarMCPGateway.execute_tool(
        "meta.create_campaign_draft",
        {"recipe_type": "NARROW", "budget_usd": 100},
        approval_granted=True,
    )
    assert res_yes.success is False
    assert res_yes.output["error"] == "NOT_CONNECTED"
    assert res_yes.approval_granted is True
