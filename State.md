# Lead Radar — machine state

- updated: 2026-08-31
- branch: codex/phase-c-budget-ledger-hardening
- mode: ops-ui-gated-live
- live_calls: master unlock ON; spend gated by DB radar_live_armed / openai_live_armed
- db_source_of_truth: lead_radar.db
- alembic_head: e4f7a1c93b20
- ops: OperationalControl singleton; UI toggles on Radar/System
- env_master: scrapecreators + EXTERNAL unlock; schedule OFF; manual only; AI hybrid; OpenAI master ON
- runtime: full app.main (web+bot+notifications) — not web-only
- notify: Telegram delivery when provider live; prior --once used NullNotifier
- pilot_note: aiko 5cr leads 29-38 in DB; MonitorRun missing for that run; next UI scan writes run
- meta_live: KEEP OFF
- tests_focus: test_operational_controls + test_live_scan_guard passed
