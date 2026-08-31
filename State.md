# Lead Radar — machine state

- updated: 2026-08-31
- branch: codex/phase-c-budget-ledger-hardening
- mode: ops-ui-gated-live
- live_calls: master unlock ON; spend gated by DB radar_live_armed / openai_live_armed
- db_source_of_truth: lead_radar.db
- alembic_head: f1a8c3e74b90
- ops: OperationalControl singleton; UI toggles on Radar/System
- env_master: scrapecreators + EXTERNAL unlock; schedule OFF; manual only; AI hybrid; OpenAI master ON
- runtime: full app.main (web+bot+notifications) — not web-only
- rattan: portfolio = explicit Competitor.vertical; taxonomy labels signals only; no auto-enroll; stub classifier deleted
- rattan_ui: /rattan empty until enroll; competitors vertical select + add form
- meta_live: KEEP OFF
- tests: 318 passed, 1 skipped
- pending_user: enroll rattan IG handles (none specified yet)
