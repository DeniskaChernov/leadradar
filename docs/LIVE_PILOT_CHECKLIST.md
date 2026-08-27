# Lead Radar V6 — Controlled Live Pilot Checklist

## Pre-Pilot Preparation
- [ ] 1. Run readiness check: `python -m scripts.live_readiness_check`
- [ ] 2. Create manual backup: `python scripts/backup_database.py`
- [ ] 3. Verify target competitors in `.env` (e.g. `COMPETITORS=aiko.uz,chinar.uz`)
- [ ] 4. Verify budget limits:
  - `OPENAI_DAILY_REQUEST_LIMIT=25`
  - `INSTAGRAM_DAILY_REQUEST_LIMIT=100`
  - `INSTAGRAM_MAX_UNITS_PER_SCAN=8`
- [ ] 5. Set security unlock flag: `EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS`
- [ ] 6. Enable live OpenAI calls if desired: `OPENAI_LIVE_CALLS_ENABLED=true`
- [ ] 7. Launch application:
  ```bash
  python -m app.main
  ```

## Live Monitoring Drill
- [ ] 1. Trigger manual scan via Telegram bot: `/scan`
- [ ] 2. Verify immediate Telegram notification received (`🔔 Новый сигнал`).
- [ ] 3. Verify message is edited after AI analysis finishes (`🔥 HOT 91/100`).
- [ ] 4. Open Web App: `http://127.0.0.1:8000/`
- [ ] 5. Verify venue openings page: `http://127.0.0.1:8000/openings`
- [ ] 6. Test AI Agent assistant drawer by asking *"Why is this lead HOT?"*

## Rollback Procedure
If live pilot needs to be paused or restored:
- [ ] 1. Pause scan schedule: set `LEAD_SEARCH_ENABLED=false` in `.env`
- [ ] 2. Restore database if needed: `python scripts/restore_database.py`
