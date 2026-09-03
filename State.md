# Lead Radar — machine state

- updated: 2026-09-03T17:15+05
- ui: 13.29.5-contrast
- first_live_pilot: DONE run=630; spend −16 PROVIDER_CONFIRMED; UNCERTAIN=0
- rollback: radar=OFF; openai=OFF; EXTERNAL_KILL_SWITCH=true → spend unlocked=false
- schedule=OFF; manual_only=ON; meta=OFF
- C7: FIXED comment page-by-page + scan_budget tracks PROVIDER_CONFIRMED credits (not page counts)
- tests: spend_semantics + cost_safe green; overshoot stops before page 2
- tip: commit C7 when asked; no live spend without explicit allow
