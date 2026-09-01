# Lead Radar — machine state

- updated: 2026-09-01
- branch: codex/phase-c-budget-ledger-hardening
- deploy_target: LOCAL ONLY
- mode: ops-ui-gated-live
- runtime: full app.main running (web+bot+notifications)
- alembic_head: f1a8c3e74b90
- ui: 13.8.7-openai-toggle
- audit_fixes: parse_display_dt; schedule_contact; scan_plan ops gate; openai_spend api_key
- gpt_web: hybrid_lead_service + live_gate; analyze-local rules-only; retry-pending/single analyze use OpenAI when armed
- openai_schema: LeadScoreFactors closed model; analysis_version=3.2; reasoning=low; max_output_tokens=2000
- openai_pilot_2026-09-01: leads 39/40 -> NOT_LEAD (5/10) via OpenAI; openai disarmed after
- openai_queue_2026-09-01: retry-pending 7/7 via hybrid; AI_PENDING=0
- rattan_scan_2026-09-01: MonitorRun#2 SUCCESS; budget 5 spent 5; competitors aiko+chinar+mebel__house__; comments_created=30 baseline; budget_stop chinar
- rattan_portfolio: chinar.uz + mebel__house__ ARTIFICIAL_RATTAN active; aiko FURNITURE active
- meta_live: KEEP OFF
- after_ops: radar OFF, openai OFF
