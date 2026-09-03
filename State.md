# Lead Radar — machine state

- updated: 2026-09-03T17:00+05
- ui: 13.29.5-contrast
- head: 4a15590
- first_live_pilot: DONE run=630; spend −16 PROVIDER_CONFIRMED; UNCERTAIN=0
- rollback: radar=OFF; openai=OFF; EXTERNAL_KILL_SWITCH=true → spend unlocked=false
- ig_live_cfg may still be true but gated by kill switch
- schedule=OFF; manual_only=ON; meta=OFF
- open: pagination overshoot vs scan_cap=5 (reserved 2 → charged 15)
- tip: next=fix comment pagination overshoot OR leave until next explicit allow
