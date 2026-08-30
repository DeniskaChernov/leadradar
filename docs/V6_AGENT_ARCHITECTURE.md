# Lead Radar V6 — planned Agent/MCP contract (NOT_CONNECTED)

Этот документ описывает целевой контракт, а не текущее подключение. В репозитории есть
типизированные определения `LeadRadarMCPGateway`, но их выполнение возвращает `NOT_CONNECTED`;
`AgentSessionAssistant` отсутствует, а `/api/agent/query` честно отвечает HTTP 503.

## 1. Target system overview

```text
User / Manager Query (Web UI or Telegram)
       ↓
Grounded Agent service (planned)
       ↓
LeadRadarMCPGateway (app/services/mcp_gateway_service.py)
       ↓
├── Read Tools (lead.*, audience.*, competitor.*, rattan.*, google.*) -> Auto-Execute
└── Write Tools (crm.*, meta.*) -> Human Approval Check
       ↓
Database + Evidence Graph + Catalog Facts
```

До подключения реальных DB-backed tools этот контур нельзя считать реализованным или
использовать как доказательство production readiness.

## 2. Security & Factuality Principles
1. **Facts First**: GPT is a reasoning layer, NOT a fact generator. All facts originate from `PublicSignal`, `Evidence`, and SQLite DB.
2. **Approval Gating**: Any write action that changes CRM data or spends budget MUST be explicitly approved by a manager.
3. **No Unrestricted Access**: The agent communicates exclusively through typed MCP tool schemas. No raw SQL or shell access.
