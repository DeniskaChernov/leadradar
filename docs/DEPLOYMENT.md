# Lead Radar — Deployment Runbook (Stage 9)

## Режимы запуска

| Режим | Команда | Когда использовать |
|-------|---------|-------------------|
| Web-only CRM | `python -m app.main --web-only` | Railway, публичный Mini App без Telegram polling |
| Full stack | `python -m app.main` | Локальный сервер с Telegram bot + web |

Railway и Docker по умолчанию используют **web-only**.

## Health probes

| Endpoint | Назначение | Ожидание |
|----------|------------|----------|
| `GET /health` | Liveness (процесс жив) | `200`, `ok: true` |
| `GET /ready` | Readiness (БД + Alembic head + drift) | `200` если готов, иначе `503` |

Railway: `healthcheckPath=/ready` в `railway.json`.

## Обязательные переменные (production)

```env
DATABASE_URL=postgresql+asyncpg://...
WEB_HOST=0.0.0.0
WEB_PUBLIC_URL=https://your-domain.example
WEB_AUTH_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ADMIN_CHAT_IDS=...
TELEGRAM_MANAGER_CHAT_IDS=...
TELEGRAM_VIEWER_CHAT_IDS=...
EXTERNAL_KILL_SWITCH=true
INSTAGRAM_PROVIDER=replay
```

Railway автоматически задаёт `PORT` — приложение читает его и переопределяет `WEB_PORT`.

## PostgreSQL

- URL `postgres://` нормализуется в `postgresql+asyncpg://` (`app/db/session.py`).
- SQLite backup на старте пропускается для PostgreSQL.
- Backup/restore для PG — через managed layer провайдера (см. `docs/BACKUP_RESTORE_RUNBOOK.md` для SQLite).

## Стартовая последовательность

1. `backup_sqlite_database()` (только SQLite)
2. `alembic upgrade head`
3. Catalog/market sync
4. Uvicorn web server

Проверка перед live pilot: `python scripts/live_readiness_check.py`.

## Логи

- Text (default): стандартный формат Python logging.
- JSON: `LOG_FORMAT=json` для structured logs в production.

## Откат

1. Откатить deploy на предыдущую версию образа.
2. При необходимости: `alembic downgrade -1` (только если миграция обратима).
3. Проверить `GET /ready` → `200`.

## Безопасность

- Публичный доступ требует `WEB_AUTH_ENABLED=true` и HTTPS `WEB_PUBLIC_URL`.
- В dev без auth mutating `POST /api/*` блокируется без `WEB_MANAGER_ID`.
- `/api/docs` скрыт когда auth выключен.
