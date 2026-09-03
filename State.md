# Lead Radar — machine state

- updated: 2026-09-03T15:55+05
- ui: 13.29.3-bugfix
- branch: codex/phase-c-budget-ledger-hardening
- head_before: c189846
- head_after: 915f697
- p0: pilot-readiness+policy-failclosed+freshness+arm-no-openai
- pytest_sqlite_local: 495 passed, 2 skipped
- github_ci: GREEN https://github.com/DeniskaChernov/leadradar/actions/runs/33746562899
- integrity: OK
- pilot_verdict: NOT READY
- remaining_blockers: MONITOR_SCHEDULE_ENABLED=true; INSTAGRAM_MANUAL_LIVE_SCAN_ONLY=false; active>1; operator env
- live: OFF (ops)
- scheduler_config: ON locally (blocks pilot)
- openai: OFF
- meta: OFF
- tip: no live scan; set schedule=false manual_only=true then confirm freshness+arm
