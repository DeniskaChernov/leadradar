# Lead Radar — machine state

- updated: 2026-08-31
- branch: codex/phase-c-budget-ledger-hardening
- mode: offline-hardening → pilot-prep
- live_calls: forbidden until explicit unlock
- external_kill_switch: enabled
- db_source_of_truth: lead_radar.db
- alembic_head: d9e4b1c82a70
- tests: 321 passed, 1 skipped; ruff clean
- ui: 13.6.0-system-pass — AI routing catalog.recommend, system cockpit, rattan-metrics, retry AI_PENDING
- agent: intent-first routing; catalog.recommend read tool; human synthesis
- bot: /pending, WebApp deep link «🌐 Карточка», help sync
- spend: ProviderCallUncertainError blocks fallback after call_started; AI→UNCERTAIN not finalize(1)
- ci_status: GREEN 2/2 (59a8e33, run 33380716448; prior 9bf6dff alembic fix)
- note: local .env may still point at stale ci-test-fresh.db — use lead_radar.db for pilot
- next: await explicit user unlock for 5-10 credit Radar pilot on @aiko.uz
- meta_live: KEEP OFF
- phase9: CI green done; real pilot still required
