# Lead Radar — machine state

- updated: 2026-08-31
- branch: codex/phase-c-budget-ledger-hardening
- mode: offline-hardening → pilot-prep
- live_calls: forbidden until explicit unlock
- external_kill_switch: enabled
- db_source_of_truth: lead_radar.db
- alembic_head: d9e4b1c82a70
- tests: 314+ (local sqlite); postgres concurrency test skips locally, runs in CI
- ruff: clean
- ci_status: GREEN 2/2 (9bf6dff, run 33372689720)
- master_active_phase: 9-pilot-prep
- next: run prepare_controlled_pilot; ask user for 5-10 credit live unlock
- meta_live: KEEP OFF
- phase9: CI green done; real pilot still required
