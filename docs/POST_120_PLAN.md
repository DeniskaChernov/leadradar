# Lead Radar — план после 120/120

Статус: **offline ready**. Live-вызовы запрещены до явного разрешения.

Предыдущий план: `docs/SYSTEM_IMPROVEMENT_PLAN.md` — **120/120** ✅ (commit `6fba631`).

## A. Phase 9 closeout (docs) — в работе / закрыто

- [x] A1. `PROJECT_STATUS.md` → WAVE18 / Phase 9 offline ЗАВЕРШЁН
- [x] A2. `ROADMAP.md` → Stage 9 ГОТОВО, Stage 10 gated
- [x] A3. Ссылки на Railway / PG / backup / CI quality gates
- [x] A4. Push + PR https://github.com/DeniskaChernov/leadradar/pull/2
- [x] A5. Branch protection on `main`: required checks `offline-quality-gate (sqlite)` + `(postgres)`; enforce_admins; no force-push (2026-09-03)

## B. Controlled live pilot prep (без live calls)

- [x] B1. Authoritative `PilotReadinessService` + fail-closed `prepare_controlled_pilot`
- [x] B2. `prepare_controlled_pilot --competitor aiko.uz --credits 5` → **READY** (2026-09-03)
- [x] B3. Manual backup создан (`scripts/backup_database.py`); полный restore-drill — по запросу
- [x] B4. Pilot competitor: `@aiko.uz` only after arm; cap=5; schedule OFF; manual-only ON
- [x] B5. Unseen gates PASS (lead/rattan/audience)
- [x] B6. `arm_controlled_pilot --competitor aiko.uz --credits 5` → Radar ON, OpenAI OFF, active=1
- [x] B7. Telegram manager chat для pilot: `TELEGRAM_MANAGER_CHAT_IDS` (локально; delivery через manager IDs; readiness fail-closed)

## C. Phase 10 — только после явного «разрешаю live»

- [x] C0. Env prep: schedule OFF, manual-only ON, OpenAI live OFF (rules-only first)
- [x] C1. Unlock intentional for pilot (`EXTERNAL_KILL_SWITCH=false` + `EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS`)
- [x] C2. Ручной `--once` scan cap=5 (run 630): live SC calls; wallet −16 PROVIDER_CONFIRMED; UNCERTAIN=0
- [x] C3. OpenAI hybrid только если unseen PASS + **explicit** arm тумблер после Radar proof
- [x] C4. Telegram delivery smoke (1 manager)
- [x] C5. Meta Custom Audience confirmed export (PAUSED + phone SHA-256; gate NOT_CONNECTED без unlock)
- [x] C6. После первого pilot scan: Radar disarmed + `EXTERNAL_KILL_SWITCH=true` (2026-09-03)
- [x] C7. Fix scan_cap overshoot: comment page-by-page + PROVIDER_CONFIRMED credits (`1a74983`)

## D. Product backlog (offline, по приоритету)

- [x] D1. Meta Custom Audience Graph adapter (PAUSED audience + users) за fail-closed gate
- [x] D2. Playwright browser E2E (Chromium; CI installs browsers; HTTP smoke сохранён)
- [x] D3. Audience golden expansion beyond current unseen (`unseen:v2`, 76 cases / 210 decisions)
- [x] D4. Service worker для PWA offline shell (`/sw.js`, cache `13.29.6-pwa`)
- [x] D5. Find-leads UI redesign (`/radar` wizard → human CRM shell, cache `13.45.0-ops-live`)

## E. Outside this plan (не фейкать)

- Coming Soon источники поиска (Telegram/TikTok/Facebook/Maps/OLX/Glotr/тендеры/Web) — отдельные интеграции
- Push/merge PR + production Railway — доставка ветки
- Повторный live pilot — только после «разрешаю live»

## Правило

Любой пункт C требует явной фразы пользователя вроде «разрешаю live» / «делай pilot».
Пункты A/B/D можно делать в offline режиме без внешних spend.
