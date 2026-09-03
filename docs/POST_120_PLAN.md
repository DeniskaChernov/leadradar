# Lead Radar — план после 120/120

Статус: **offline ready**. Live-вызовы запрещены до явного разрешения.

Предыдущий план: `docs/SYSTEM_IMPROVEMENT_PLAN.md` — **120/120** ✅ (commit `6fba631`).

## A. Phase 9 closeout (docs) — в работе / закрыто

- [x] A1. `PROJECT_STATUS.md` → WAVE18 / Phase 9 offline ЗАВЕРШЁН
- [x] A2. `ROADMAP.md` → Stage 9 ГОТОВО, Stage 10 gated
- [x] A3. Ссылки на Railway / PG / backup / CI quality gates
- [x] A4. Push + PR https://github.com/DeniskaChernov/leadradar/pull/2
- [ ] A5. Branch protection: required checks `offline-quality-gate` (sqlite+postgres) — вручную в GitHub Settings

## B. Controlled live pilot prep (без live calls)

- [x] B1. Authoritative `PilotReadinessService` + fail-closed `prepare_controlled_pilot`
- [x] B2. `prepare_controlled_pilot --competitor aiko.uz --credits 5` → **READY** (2026-09-03)
- [x] B3. Manual backup создан (`scripts/backup_database.py`); полный restore-drill — по запросу
- [x] B4. Pilot competitor: `@aiko.uz` only after arm; cap=5; schedule OFF; manual-only ON
- [x] B5. Unseen gates PASS (lead/rattan/audience)
- [x] B6. `arm_controlled_pilot --competitor aiko.uz --credits 5` → Radar ON, OpenAI OFF, active=1
- [ ] B7. Отдельный Telegram manager chat для pilot — решение менеджера

## C. Phase 10 — только после явного «разрешаю live»

- [x] C0. Env prep: schedule OFF, manual-only ON, OpenAI live OFF (rules-only first)
- [ ] C1. Confirm unlock remains intentional (`EXTERNAL_KILL_SWITCH=false` + `EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS`)
- [ ] C2. Ручной `/scan` с лимитом credits=5; reconciliation ledger
- [ ] C3. OpenAI hybrid только если unseen PASS + **explicit** arm тумблер после Radar proof
- [ ] C4. Telegram delivery smoke (1 manager)
- [x] C5. Meta Custom Audience confirmed export (PAUSED + phone SHA-256; gate NOT_CONNECTED без unlock)
- [ ] C6. После пилота: kill switch ON, отчёт в `docs/` + `State.md`

## D. Product backlog (offline, по приоритету)

- [x] D1. Meta Custom Audience Graph adapter (PAUSED audience + users) за fail-closed gate
- [ ] D2. Playwright browser E2E (сейчас HTTP-level e2e)
- [ ] D3. Audience golden expansion beyond current unseen
- [ ] D4. Service worker для PWA offline shell (сейчас только manifest)

## Правило

Любой пункт C требует явной фразы пользователя вроде «разрешаю live» / «делай pilot».
Пункты A/B/D можно делать в offline режиме без внешних spend.
