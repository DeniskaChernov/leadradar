# Lead Radar — machine state

- updated: 2026-08-31
- branch: codex/phase-c-budget-ledger-hardening
- mode: offline-hardening → pilot-prep
- live_calls: forbidden until explicit unlock
- external_kill_switch: enabled
- db_source_of_truth: lead_radar.db
- alembic_head: d9e4b1c82a70
- tests: 316 passed, 1 skipped (local sqlite); postgres concurrency test skips locally, runs in CI
- ruff: clean
- ui: pilot-cockpit 13.3.0 — nav 5+5, quick-actions, scan-quick modal; uncommitted→commit pending
- spend: ProviderCallUncertainError blocks fallback after call_started; AI→UNCERTAIN not finalize(1)
- ci_status: GREEN 2/2 (59a8e33, run 33380716448; prior 9bf6dff alembic fix)
- note: local .env may still point at stale ci-test-fresh.db — use lead_radar.db for pilot
- next: await explicit user unlock for 5-10 credit Radar pilot on @aiko.uz
- meta_live: KEEP OFF
- phase9: CI green done; real pilot still required
