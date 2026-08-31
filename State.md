# Lead Radar — machine state

- updated: 2026-08-31
- branch: codex/phase-c-budget-ledger-hardening
- mode: offline-hardening
- live_calls: forbidden
- external_kill_switch: enabled
- db_source_of_truth: lead_radar.db
- alembic_head: c8f3a1d57b20
- tests: 314 passed (local sqlite)
- ruff: clean
- ci_status: pending after hardening push (was red on postgres DuplicateTable uq_contacts_platform)
- master_active_phase: 9-hardening
- next: confirm GitHub CI 2/2 green; then 5-10 credit controlled Radar pilot
- p0_fixed: initial migration unique names; ScanBudget default vs cycle; started+unknown→UNCERTAIN; pg advisory lock; economics credit accuracy; postgres backup not auto-true
- meta_live: KEEP OFF until durable approval/idempotency/ledger
- phase9: NOT complete until CI green + spend semantics proven on real pilot
