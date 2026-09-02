# Railway Deployment

Lead Radar деплоится на Railway через Dockerfile (`railway.json`).

## Конфигурация

| Файл | Назначение |
|------|------------|
| `railway.json` | builder, startCommand, healthcheck |
| `Dockerfile` | Python 3.12-slim, `--web-only` |
| `docs/DEPLOYMENT.md` | env vars, security |

## Build & Start

```json
{
  "build": { "builder": "DOCKERFILE" },
  "deploy": {
    "startCommand": "python -m app.main --web-only",
    "healthcheckPath": "/ready",
    "healthcheckTimeout": 30
  }
}
```

Railway задаёт `PORT` — приложение читает его и биндит Uvicorn.

## Обязательные переменные (Railway Variables)

```env
DATABASE_URL=postgresql+asyncpg://...
WEB_PUBLIC_URL=https://<service>.up.railway.app
WEB_AUTH_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ADMIN_CHAT_IDS=...
EXTERNAL_KILL_SWITCH=true
INSTAGRAM_PROVIDER=replay
```

Опционально:

```env
LOG_FORMAT=json
SENTRY_DSN=
WEB_MANAGER_ID=   # только dev без auth
```

## Healthcheck

- **Liveness:** `GET /health`
- **Readiness (Railway):** `GET /ready` — БД, Alembic head, extended counters

Docker `HEALTHCHECK` в Dockerfile дублирует `/ready` на `PORT`.

## Deploy flow

1. Push в connected branch → Railway build из Dockerfile.
2. `alembic upgrade head` на старте контейнера.
3. Uvicorn слушает `0.0.0.0:$PORT`.
4. Railway routing → public URL.

## Rollback

Railway Dashboard → Deployments → Redeploy previous successful deploy.

При schema drift: см. `docs/POSTGRESQL_MIGRATION_CHECKLIST.md` §6.

## Railpack vs Dockerfile

Текущий production path — **Dockerfile** (явный контроль Python 3.12, HEALTHCHECK).
Railpack/Nixpacks не используется — `railway.json` указывает `"builder": "DOCKERFILE"`.

## Локальная проверка образа

```bash
docker build -t lead-radar .
docker run --rm -p 8000:8000 -e DATABASE_URL=sqlite+aiosqlite:///./data.db lead-radar
curl http://127.0.0.1:8000/ready
```

Перед live: `python scripts/live_readiness_check.py`.
