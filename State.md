# Lead Radar — machine state

- updated: 2026-08-31
- branch: codex/phase-c-budget-ledger-hardening
- mode: offline-hardening
- live_calls: forbidden
- external_kill_switch: enabled
- db_source_of_truth: lead_radar.db
- alembic_head: d9e4b1c82a70 (local; uncommitted migrate + env include_object)
- tests: 314 passed (local sqlite)
- ruff: clean
- alembic_check: No new upgrade operations detected (check_constraints ignored in include_object)
- ci_status: pending push — uncommitted: alembic/env.py + d9e4b1c82a70
- master_active_phase: 9-hardening
- next: commit+push alembic fix → confirm GitHub CI 2/2 green → 5-10 credit Radar pilot
- p0_fixed: unique names; ScanBudget; UNCERTAIN; pg lock; economics accuracy; backup marker; ck name drift
- meta_live: KEEP OFF
- phase9: NOT complete until CI green + real pilot
