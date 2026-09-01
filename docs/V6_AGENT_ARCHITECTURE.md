# Lead Radar V6 — Grounded Agent & MCP Gateway

Read tools подключены к SQLite через `MCPReadToolService`. Write tools (`crm.*`, `meta.*`)
остаются за Human-in-the-Loop и пока возвращают `NOT_CONNECTED`.

## 1. System overview

```text
User / Manager Query (Web UI or Telegram)
       ↓
AgentSessionService (offline deterministic synthesis)
       ↓
LeadRadarMCPGateway.execute_tool_async
       ↓
├── Read Tools (lead.*, audience.*, competitor.*, rattan.*, google.*) -> DB-backed auto execute
└── Write Tools (crm.*, meta.*) -> approval check -> NOT_CONNECTED
       ↓
Database + Evidence Graph
```

`/api/agent/query` возвращает grounded ответ только из tool output и `evidence_ids`.
GPT-слой не вызывается в offline-hardening режиме: синтез детерминированный.

## 2. Security & Factuality Principles
1. **Facts First**: все факты из `PublicSignal`, `Evidence`, SQLite. Agent не выдумывает SKU, stock, discount.
2. **Approval Gating**: write tools требуют explicit approval менеджера.
3. **Allowed Audiences**: `audience.dna` принимает только ACTIVE slugs из `AllowedAudienceRegistry`.
4. **Membership Evidence**: `AudienceMembershipResolver` возвращает persisted evidence_ids.
