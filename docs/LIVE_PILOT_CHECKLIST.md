# Lead Radar — Controlled Live Pilot Checklist

**Gate:** выполнять только после явного разрешения. Offline prep (раздел 0) — без live.

См. также: `docs/POST_120_PLAN.md`, `docs/DEPLOYMENT.md`, `scripts/live_readiness_check.py`.

## 0. Offline prep (без внешних вызовов)

- [ ] 1. Unseen gates PASS на `/system`
- [ ] 2. `python -m ruff check .` и `python -m pytest -q`
- [ ] 3. `python -m scripts.check_data_integrity`
- [ ] 4. `python -m scripts.live_readiness_check` → записать результат в `State.md`
- [ ] 5. `python -m scripts.prepare_controlled_pilot` (dry)
- [ ] 6. Manual backup: `python scripts/backup_database.py`
- [ ] 7. Выбраны 1–2 конкурента; `INSTAGRAM_MAX_UNITS_PER_SCAN` ≤ 8–10
- [ ] 8. Отдельный Telegram manager chat id в env

## 1. Unlock (только с разрешением)

- [ ] 1. `EXTERNAL_KILL_SWITCH=false`
- [ ] 2. `EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS`
- [ ] 3. `INSTAGRAM_LIVE_CALLS_ENABLED=true` (если нужен Radar)
- [ ] 4. `OPENAI_LIVE_CALLS_ENABLED=true` (если нужен hybrid GPT) + arm тумблер на `/system`
- [ ] 5. Бюджеты:
  - `OPENAI_DAILY_REQUEST_LIMIT=25` (или меньше)
  - `INSTAGRAM_DAILY_REQUEST_LIMIT` с жёстким дневным cap
  - `INSTAGRAM_MAX_UNITS_PER_SCAN=8`
- [ ] 6. Запуск: `python -m app.main` или `--web-only` + bot отдельно

## 2. Live smoke

- [ ] 1. Ручной scan (`/scan` или UI) — проверить ledger credits
- [ ] 2. Telegram: новый сигнал → edit после анализа
- [ ] 3. Web: `/leads` funnel (take → stage), kanban drag-drop
- [ ] 4. `/economics` — confirmed vs estimated credits
- [ ] 5. Agent drawer: grounded вопрос по HOT-лиду
- [ ] 6. Reconciliation: нет `UNCERTAIN` без разбора

## 3. Rollback

- [ ] 1. `EXTERNAL_KILL_SWITCH=true` (или выключить live flags)
- [ ] 2. Disarm OpenAI/Radar тумблеры на `/system`
- [ ] 3. При необходимости: `python scripts/restore_database.py`
- [ ] 4. Запись итога в `State.md` + короткий отчёт в `docs/`

## 4. Meta (опционально, отдельное разрешение)

- [ ] Dry-run export recipe на `/system`
- [ ] Confirmed Custom Audience export — **не реализован** (NOT_CONNECTED); не включать без adapter
