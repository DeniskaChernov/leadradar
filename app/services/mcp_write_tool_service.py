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
from app.services.project_file_service import ProjectFileService

WRITE_TOOL_NAMES = frozenset(
    {
        "crm.assign_lead",
        "meta.create_campaign_draft",
        "competitor.manage",
        "project.write_file",
    }
)


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
        from app.services.crm_service import CRMService

        self.crm = CRMService(session_factory)
        self.project_files = ProjectFileService()

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
        if tool_name == "competitor.manage":
            return await self.competitor_manage(
                str(arguments["handle"]),
                active=arguments.get("active"),
                tier=str(arguments["tier"]) if arguments.get("tier") else None,
                display_name=str(arguments["display_name"]) if arguments.get("display_name") else "",
                category=str(arguments["category"]) if arguments.get("category") else "DIRECT",
            )
        if tool_name == "project.write_file":
            return await self.project_write_file(
                str(arguments["relative_path"]),
                str(arguments["content"]),
                mode=str(arguments.get("mode") or "overwrite"),
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

    async def competitor_manage(
        self,
        handle: str,
        *,
        active: bool | None = None,
        tier: str | None = None,
        display_name: str = "",
        category: str = "DIRECT",
    ) -> dict[str, Any]:
        normalized = handle.strip().lstrip("@").lower()
        if not normalized:
            return {"error": "INVALID_HANDLE", "message": "handle обязателен"}
        from sqlalchemy import select

        from app.db.models import Competitor

        async with self.crm.session_factory() as session:
            existing = await session.scalar(
                select(Competitor).where(Competitor.normalized_handle == normalized)
            )
        if existing is None:
            competitor = await self.crm.add_competitor(
                normalized,
                display_name=display_name or normalized,
                category=category,
                tier=tier or "B",
            )
            if active is False:
                competitor = await self.crm.update_competitor(competitor.id, active=False)
            return {
                "competitor_id": competitor.id,
                "handle": competitor.normalized_handle,
                "active": competitor.active,
                "created": True,
            }
        competitor = await self.crm.update_competitor(
            existing.id,
            active=active if active is not None else True,
            tier=tier,
        )
        return {
            "competitor_id": competitor.id,
            "handle": competitor.normalized_handle,
            "active": competitor.active,
            "created": False,
        }

    async def project_write_file(
        self,
        relative_path: str,
        content: str,
        *,
        mode: str = "overwrite",
    ) -> dict[str, Any]:
        try:
            result = self.project_files.write_file(relative_path, content, mode=mode)
        except ValueError as exc:
            return {"error": "INVALID_PATH", "message": str(exc)}
        return {
            "relative_path": result.relative_path,
            "bytes_written": result.bytes_written,
            "mode": result.mode,
        }
