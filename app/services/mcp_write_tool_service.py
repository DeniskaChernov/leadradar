"""Approval-gated write handlers для MCP tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.services.lead_workflow_service import (
    LeadAlreadyAssignedError,
    LeadWorkflowError,
    LeadWorkflowService,
)
from app.services.meta_ads_service import MetaAdsService

WRITE_TOOL_NAMES = frozenset({"crm.assign_lead", "meta.create_campaign_draft"})


class MCPWriteToolService:
    """Write tools with mandatory human approval at gateway level."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        hot_threshold: int,
        settings: Settings | None = None,
        meta_ads: MetaAdsService | None = None,
    ) -> None:
        resolved_settings = settings or get_settings()
        self.workflow = LeadWorkflowService(session_factory, hot_threshold=hot_threshold)
        self.meta_ads = meta_ads or MetaAdsService(resolved_settings)

    async def dispatch(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "crm.assign_lead":
            return await self.crm_assign_lead(
                int(arguments["lead_id"]),
                int(arguments["manager_id"]),
            )
        if tool_name == "meta.create_campaign_draft":
            return await self.meta_create_campaign_draft(
                str(arguments["recipe_type"]),
                float(arguments["budget_usd"]),
            )
        raise ValueError(f"Unsupported write tool: {tool_name}")

    async def crm_assign_lead(self, lead_id: int, manager_id: int) -> dict[str, Any]:
        try:
            lead = await self.workflow.assign_manager(lead_id, manager_id)
        except LeadAlreadyAssignedError as exc:
            return {
                "error": "ALREADY_ASSIGNED",
                "lead_id": lead_id,
                "assigned_manager_id": exc.manager_id,
            }
        except LeadWorkflowError as exc:
            return {"error": "WORKFLOW_ERROR", "lead_id": lead_id, "message": str(exc)}
        return {
            "lead_id": lead.id,
            "contact_id": lead.contact_id,
            "status": lead.status.value,
            "assigned_manager_id": lead.assigned_manager_telegram_id,
        }

    async def meta_create_campaign_draft(self, recipe_type: str, budget_usd: float) -> dict[str, Any]:
        return await self.meta_ads.create_campaign_draft(recipe_type, budget_usd)
