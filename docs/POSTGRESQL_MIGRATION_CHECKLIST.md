# PostgreSQL — Production Migration Checklist

Чеклист перед переводом Lead Radar с SQLite на managed PostgreSQL (Railway, Neon и т.п.).

## 1. Подготовка

- [ ] Production URL: `postgresql+asyncpg://user:pass@host:5432/dbname`
- [ ] `DATABASE_URL` в Railway secrets (не в git)
- [ ] Backup SQLite: `python scripts/backup_database.py`
- [ ] Зафиксировать Alembic head: `python -m alembic current`
- [ ] CI postgres matrix зелёный на текущем HEAD

## 2. Staging dry-run

- [ ] Поднять staging с `DATABASE_URL=postgresql+asyncpg://...`
- [ ] `python -m alembic upgrade head` (дважды — идемпотентность)
- [ ] `python -m alembic check`
- [ ] `python -m pytest -q`
- [ ] `python -m scripts.check_data_integrity`
- [ ] `GET /ready` → 200

## 3. Миграция данных (если нужен перенос из SQLite)

Lead Radar не шипит автоматический SQLite→PG dump. Варианты:

| Подход | Когда |
|--------|-------|
| Fresh PG + catalog sync | Новый pilot, данные можно пересобрать |
| pgloader / custom ETL | Нужна история лидов и contact_events |

При ETL обязательно сохранить:

- `contacts`, `comments`, `posts`, `leads`, `public_signals`, `evidence`
- `contact_events` (immutable history)
- `interest_evidence.interest_key` uniqueness

После импорта: `check_data_integrity` → 0 duplicates.

## 4. Production cutover

- [ ] Maintenance window / read-only mode (опционально)
- [ ] Deploy с `DATABASE_URL` PostgreSQL
- [ ] Логи: нет ошибок `alembic upgrade`
- [ ] `GET /ready` → 200 в течение 60s
- [ ] Smoke: login Mini App, `/leads`, `/system`
- [ ] Telegram bot (если full stack): `/stats`, `/hot`

## 5. Post-cutover (24h)

- [ ] Мониторинг `/ready` (Railway healthcheck)
- [ ] Нет роста `AI_PENDING` / `uncertain_reservations`
- [ ] Backup policy провайдера включена (daily snapshot)
- [ ] SQLite backup на PG **не** используется (`backup_sqlite_database` пропускается)

## 6. Rollback

1. Откат deploy на предыдущий образ (SQLite env).
2. Или восстановить PG snapshot провайдера.
3. `alembic downgrade -1` только если миграция обратима и данные не повреждены.

## Связанные документы

- `docs/DEPLOYMENT.md` — env и health probes
- `docs/BACKUP_RESTORE_RUNBOOK.md` — SQLite drill
- `docs/RAILWAY.md` — Railway deploy
