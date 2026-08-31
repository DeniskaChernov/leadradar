# Lead Radar — machine state

- updated: 2026-08-31
- branch: codex/phase-c-budget-ledger-hardening
- mode: ops-ui-gated-live
- live_calls: master unlock ON; spend gated by DB radar_live_armed / openai_live_armed
- db_source_of_truth: lead_radar.db
- alembic_head: f1a8c3e74b90
- ops: OperationalControl singleton; UI toggles on Radar/System
- env_master: scrapecreators + EXTERNAL unlock; schedule OFF; manual only; AI hybrid; OpenAI master ON
- runtime: full app.main (web+bot+notifications) — restart pending after UI/notif fixes
- rattan: portfolio = explicit Competitor.vertical; taxonomy labels signals only; no auto-enroll
- notif_ui: /system#uncertain-notifications resolve API; honest Telegram readiness copy
- ui_polish: rattan RU empty-states Lucide; radar RU; base nav competitors; cache 13.8.2-ops-ui
- meta_live: KEEP OFF
- tests_focus: phase8 + notifications + web_theme
- pending_user: enroll rattan IG handles; commit/push optional
