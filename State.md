# Lead Radar — machine state

- updated: 2026-08-30
- branch: codex/phase-c-budget-ledger-hardening
- mode: offline-hardening
- live_calls: forbidden
- external_kill_switch: enabled
- db_source_of_truth: lead_radar.db
- db_backup: .backups/lead_radar-20260830-161013-983142.db
- alembic_head: d6b1e4f92a50
- tests: 229 passed
- ruff: passed
- compileall: passed
- integrity: passed
- schema_check: passed
- schema_drift: none
- completed_stages: 0,1,2
- active_stage: 3
- next: audit and harden workflow transactions, immutable events and idempotency
- blocked_live: Instagram, OpenAI, Telegram delivery, Meta, Google
