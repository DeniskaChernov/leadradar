# Lead Radar — machine state

- updated: 2026-08-30
- branch: codex/phase-c-budget-ledger-hardening
- mode: offline-hardening
- live_calls: forbidden
- external_kill_switch: enabled
- db_source_of_truth: lead_radar.db
- db_backup: .backups/lead_radar-20260830-161013-983142.db
- alembic_head: d6b1e4f92a50
- tests: 223 passed
- ruff: passed
- compileall: passed
- integrity: passed
- schema_check: failed
- schema_drift: products.vertical; product/meta named unique constraints
- completed_stage: 0
- active_stage: 1
- next: repair schema drift without data loss
- blocked_live: Instagram, OpenAI, Telegram delivery, Meta, Google
