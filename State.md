# Lead Radar — machine state

- updated: 2026-08-30
- branch: codex/phase-c-budget-ledger-hardening
- mode: offline-hardening
- live_calls: forbidden
- external_kill_switch: enabled
- db_source_of_truth: lead_radar.db
- db_backup: .backups/lead_radar-20260830-165723-306046.db
- alembic_head: f2a5b8d13c70
- tests: 235 passed
- ruff: passed
- compileall: passed
- integrity: passed
- schema_check: passed
- schema_drift: none
- completed_stages: 0,1,2,3,4
- active_stage: 5
- next: calculate margin and ROI only from confirmed sale snapshots, COGS, attribution and FX
- blocked_live: Instagram, OpenAI, Telegram delivery, Meta, Google
