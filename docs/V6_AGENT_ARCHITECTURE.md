# Lead Radar V6 — OpenAI Agent Architecture & MCP Gateway

## 1. System Overview
Lead Radar features a central conversational AI Agent integrated with the OpenAI Agents SDK and an internal MCP (Model Context Protocol) tool gateway (`LeadRadarMCPGateway`).

```text
User / Manager Query (Web UI or Telegram)
       ↓
AgentSessionAssistant (app/services/agent_session_service.py)
       ↓
LeadRadarMCPGateway (app/services/mcp_gateway_service.py)
       ↓
├── Read Tools (lead.*, audience.*, competitor.*, rattan.*, google.*) -> Auto-Execute
└── Write Tools (crm.*, meta.*) -> Human Approval Check
       ↓
Database + Evidence Graph + Catalog Facts
```

## 2. Security & Factuality Principles
1. **Facts First**: GPT is a reasoning layer, NOT a fact generator. All facts originate from `PublicSignal`, `Evidence`, and SQLite DB.
2. **Approval Gating**: Any write action that changes CRM data or spends budget MUST be explicitly approved by a manager.
3. **No Unrestricted Access**: The agent communicates exclusively through typed MCP tool schemas. No raw SQL or shell access.
