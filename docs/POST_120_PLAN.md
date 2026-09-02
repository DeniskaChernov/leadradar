# Lead Radar — план после 120/120

Статус: **offline ready**. Live-вызовы запрещены до явного разрешения.

Предыдущий план: `docs/SYSTEM_IMPROVEMENT_PLAN.md` — **120/120** ✅ (commit `6fba631`).

## A. Phase 9 closeout (docs) — в работе / закрыто

- [x] A1. `PROJECT_STATUS.md` → WAVE18 / Phase 9 offline ЗАВЕРШЁН
- [x] A2. `ROADMAP.md` → Stage 9 ГОТОВО, Stage 10 gated
- [x] A3. Ссылки на Railway / PG / backup / CI quality gates
- [ ] A4. Push `6fba631` + PR (по запросу)
- [ ] A5. Branch protection: required checks `offline-quality-gate` (sqlite+postgres)

## B. Controlled live pilot prep (без live calls)

- [ ] B1. Пройти `python -m scripts.live_readiness_check` → зафиксировать статус в `State.md`
- [ ] B2. `python -m scripts.prepare_controlled_pilot` (dry, без spend)
- [ ] B3. Backup drill на staging SQLite (`docs/BACKUP_RESTORE_RUNBOOK.md` §5)
- [ ] B4. Выбрать 1–2 Tier A конкурента и дневной credit cap (≤10 units)
- [ ] B5. Unseen gates PASS на текущем `lead_analysis_version`
- [ ] B6. Отдельный Telegram manager chat для pilot

## C. Phase 10 — только после явного «разрешаю live»

- [ ] C1. `EXTERNAL_KILL_SWITCH=false` + `EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS`
- [ ] C2. Ручной `/scan` с лимитом credits; reconciliation ledger
- [ ] C3. OpenAI hybrid только если unseen PASS + arm тумблер
- [ ] C4. Telegram delivery smoke (1 manager)
- [ ] C5. Meta Custom Audience confirmed export (сейчас NOT_CONNECTED / dry-run)
- [ ] C6. После пилота: kill switch ON, отчёт в `docs/` + `State.md`

## D. Product backlog (offline, по приоритету)

- [ ] D1. Meta Custom Audience Graph adapter (PAUSED audience + users) за fail-closed gate
- [ ] D2. Playwright browser E2E (сейчас HTTP-level e2e)
- [ ] D3. Audience golden expansion beyond current unseen
- [ ] D4. Service worker для PWA offline shell (сейчас только manifest)

## Правило

Любой пункт C требует явной фразы пользователя вроде «разрешаю live» / «делай pilot».
Пункты A/B/D можно делать в offline режиме без внешних spend.
