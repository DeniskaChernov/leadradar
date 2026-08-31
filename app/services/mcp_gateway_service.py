"""
mcp_gateway_service.py — V6 Lead Radar Internal MCP Gateway & Tool Surface.

Defines the controlled tool surface and least-privilege schemas for the OpenAI Agent:
  - Read tools (lead.*, audience.*, competitor.*, rattan.*, google.*, catalog.*, analytics.*)
  - Write tools (crm.*, meta.*) with mandatory Human-in-the-Loop approval gating
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

READ_TOOL_NAMES = frozenset(
    {
        "lead.search",
        "lead.explain_score",
        "audience.dna",
        "competitor.opportunities",
        "rattan.company_analysis",
        "google.openings",
    }
)


@dataclass(frozen=True, slots=True)
class MCPToolDefinition:
    name: str
    namespace: str
    description: str
    requires_approval: bool  # True for write tools or external spend
    parameters_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_name: str
    success: bool
    output: Any
    approval_granted: bool
    trace_id: str | None = None


class LeadRadarMCPGateway:
    """Internal Gateway managing tool definitions, filtering, and approval gating."""

    _TOOLS: ClassVar[dict[str, MCPToolDefinition]] = {
        "lead.search": MCPToolDefinition(
            name="lead.search",
            namespace="lead",
            description="Поиск лидов по роли, статусу, скору и ключевым словам.",
            requires_approval=False,
            parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
        "lead.explain_score": MCPToolDefinition(
            name="lead.explain_score",
            namespace="lead",
            description="Детальное объяснение оценки скора лида по факторам и фактам (evidence).",
            requires_approval=False,
            parameters_schema={"type": "object", "properties": {"lead_id": {"type": "integer"}}},
        ),
        "audience.dna": MCPToolDefinition(
            name="audience.dna",
            namespace="lead",
            description="Извлечение профиля Audience DNA для группы контактов или сегмента.",
            requires_approval=False,
            parameters_schema={"type": "object", "properties": {"segment_slug": {"type": "string"}}},
        ),
        "competitor.opportunities": MCPToolDefinition(
            name="competitor.opportunities",
            namespace="competitor",
            description="Поиск коммерческих возможностей и неотвеченного спроса конкурента.",
            requires_approval=False,
            parameters_schema={"type": "object", "properties": {"competitor_id": {"type": "integer"}}},
        ),
        "rattan.company_analysis": MCPToolDefinition(
            name="rattan.company_analysis",
            namespace="rattan",
            description="Анализ роли участника рынка ротанга (оптовик, реселлер, производитель).",
            requires_approval=False,
            parameters_schema={"type": "object", "properties": {"company_name": {"type": "string"}}},
        ),
        "google.openings": MCPToolDefinition(
            name="google.openings",
            namespace="google",
            description="Получение очереди сигналов о новых открывающихся B2B-заведениях.",
            requires_approval=False,
            parameters_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        ),
        "crm.assign_lead": MCPToolDefinition(
            name="crm.assign_lead",
            namespace="crm",
            description="Назначение ответственного менеджера за лидом.",
            requires_approval=True,
            parameters_schema={
                "type": "object",
                "properties": {"lead_id": {"type": "integer"}, "manager_id": {"type": "integer"}},
            },
        ),
        "meta.create_campaign_draft": MCPToolDefinition(
            name="meta.create_campaign_draft",
            namespace="meta",
            description="Создание приостановленного (PAUSED) черновика кампании в Meta Ads.",
            requires_approval=True,
            parameters_schema={
                "type": "object",
                "properties": {"recipe_type": {"type": "string"}, "budget_usd": {"type": "number"}},
            },
        ),
    }

    def __init__(self, read_service: Any | None = None) -> None:
        self.read_service = read_service

    @classmethod
    def from_session_factory(cls, session_factory, *, hot_threshold: int) -> LeadRadarMCPGateway:
        from app.services.mcp_read_tool_service import MCPReadToolService

        return cls(
            MCPReadToolService(session_factory, hot_threshold=hot_threshold),
        )

    @classmethod
    def list_tools(cls, *, namespace: str | None = None) -> list[MCPToolDefinition]:
        if namespace is None:
            return list(cls._TOOLS.values())
        return [t for t in cls._TOOLS.values() if t.namespace == namespace]

    @classmethod
    def execute_tool(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        approval_granted: bool = False,
        trace_id: str | None = None,
    ) -> ToolExecutionResult:
        """Sync stub без read_service — сохраняет честный NOT_CONNECTED контракт."""
        return cls(read_service=None)._build_result(
            tool_name,
            arguments,
            approval_granted=approval_granted,
            trace_id=trace_id,
            connected=False,
        )

    async def execute_tool_async(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        approval_granted: bool = False,
        trace_id: str | None = None,
    ) -> ToolExecutionResult:
        return await self._execute(
            tool_name,
            arguments,
            approval_granted=approval_granted,
            trace_id=trace_id,
        )

    async def _execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        approval_granted: bool,
        trace_id: str | None,
    ) -> ToolExecutionResult:
        tool = self._TOOLS.get(tool_name)
        if tool is None:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output={"error": f"Tool '{tool_name}' not found"},
                approval_granted=approval_granted,
                trace_id=trace_id,
            )

        if tool.requires_approval and not approval_granted:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output={
                    "error": f"Execution of write tool '{tool_name}' requires explicit human approval."
                },
                approval_granted=False,
                trace_id=trace_id,
            )

        if tool_name in READ_TOOL_NAMES:
            if self.read_service is None:
                return self._not_connected(tool_name, approval_granted, trace_id)
            try:
                output = await self.read_service.dispatch(tool_name, arguments)
            except (KeyError, ValueError, TypeError) as exc:
                return ToolExecutionResult(
                    tool_name=tool_name,
                    success=False,
                    output={"error": "INVALID_ARGUMENTS", "message": str(exc)},
                    approval_granted=approval_granted,
                    trace_id=trace_id,
                )
            success = not (isinstance(output, dict) and output.get("error"))
            return ToolExecutionResult(
                tool_name=tool_name,
                success=success,
                output=output,
                approval_granted=approval_granted,
                trace_id=trace_id,
            )

        return self._not_connected(tool_name, approval_granted, trace_id)

    def _build_result(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        approval_granted: bool,
        trace_id: str | None,
        connected: bool,
    ) -> ToolExecutionResult:
        tool = self._TOOLS.get(tool_name)
        if tool is None:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output={"error": f"Tool '{tool_name}' not found"},
                approval_granted=approval_granted,
                trace_id=trace_id,
            )
        if tool.requires_approval and not approval_granted:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output={
                    "error": f"Execution of write tool '{tool_name}' requires explicit human approval."
                },
                approval_granted=False,
                trace_id=trace_id,
            )
        if connected and tool_name in READ_TOOL_NAMES:
            raise RuntimeError("Sync execute_tool cannot run connected read tools")
        return self._not_connected(tool_name, approval_granted, trace_id)

    @staticmethod
    def _not_connected(
        tool_name: str,
        approval_granted: bool,
        trace_id: str | None,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=tool_name,
            success=False,
            output={
                "error": "NOT_CONNECTED",
                "message": f"Tool '{tool_name}' is not connected to a real service yet.",
            },
            approval_granted=approval_granted,
            trace_id=trace_id,
        )
