# Lead Radar — Deployment Runbook (Stage 9)

## Windows + Cloudflare Quick Tunnel

Текущий рабочий сценарий — `start_cloudflare_windows.bat` с защищённым входом
по паролю. Подробная проверенная инструкция и ограничения временного адреса:
[LIVE_SETUP_2026-10-06.md](LIVE_SETUP_2026-10-06.md).

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

Railway: `healthcheckPath=/ready` в `railway.json`. Подробнее: `docs/RAILWAY.md`.

Эти probes не делают внешний Instagram/OpenAI запрос и не доказывают доступность
провайдера. `backup_present` проверяет подходящий файл рядом с настроенной SQLite;
успешное восстановление подтверждается отдельным drill.

## Диагностика процесса

app.main фиксирует режим, PID, run_id, build диагностики, время старта,
heartbeat раз в 30 секунд и терминальный результат. Для файловой SQLite receipt
лежит в `.runtime/<database filename>.lifecycle.json` рядом с БД. Запись атомарна;
предыдущая сохраняется кратким snapshot. Блокировка БД защищает receipt
активного процесса от второго экземпляра. PostgreSQL/in-memory — память на этом этапе.

Нормальное завершение — STOPPED; исключение/ненулевой код — FAILED;
отмена/KeyboardInterrupt — INTERRUPTED. OS kill не может записать finally:
следующий старт показывает прошлый RUNNING как незавершённый. Это возможно
и при штатном принудительном Windows Stop-Process; receipt не отличает его
от аварии и не устанавливает причину старой остановки. Тип исключения сохраняется,
текст и настройки соединения в receipt не записываются.

«Система → Работа сервера» показывает текущий процесс и прошлое завершение.
LOG_FORMAT=json сериализует сообщения/исключения: кавычки, переводы строк и
Windows paths не ломают JSON. Uvicorn/Alembic могут иметь собственное оформление;
весь stderr не объявляется чистым JSONL.

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

## WEB_MANAGER_ID (локальная разработка)

`WEB_MANAGER_ID` — Telegram user id менеджера, от имени которого выполняются mutating `POST /api/*`
когда `WEB_AUTH_ENABLED=false` (типичный локальный dev без Mini App auth).

```env
WEB_MANAGER_ID=123456789
```

| Режим | Поведение |
|-------|-----------|
| `WEB_AUTH_ENABLED=true` | Auth через Telegram initData или настроенный admin-пароль; `WEB_MANAGER_ID` не обязателен |
| `WEB_AUTH_ENABLED=false` + `WEB_MANAGER_ID=0` | Только loopback; используется первый admin ID, если настроен; без него mutation запрещена |
| `WEB_AUTH_ENABLED=false` + `WEB_MANAGER_ID>0` | Mutating API разрешены от имени указанного manager id |

Production: используйте `WEB_AUTH_ENABLED=true` и HTTPS `WEB_PUBLIC_URL`. `WEB_MANAGER_ID` —
только для dev/staging без auth. Значение берётся из `@userinfobot` или Telegram profile id
администратора.

## Meta Ads (optional live)

```env
META_ADS_ACCESS_TOKEN=
META_ADS_AD_ACCOUNT_ID=
META_ADS_LIVE_CALLS_ENABLED=false
```

Live calls требуют `EXTERNAL_KILL_SWITCH=false` и `EXTERNAL_LIVE_UNLOCK=ALLOW_EXTERNAL_CALLS`.
MCP tool `meta.create_campaign_draft` создаёт PAUSED campaign + adset через Graph API.

## Graceful shutdown

Linux/containers: SIGTERM/SIGINT останавливает Telegram polling, web server и фоновые задачи.
Windows dev: Ctrl+C через `KeyboardInterrupt`.

## PostgreSQL

- URL `postgres://` нормализуется в `postgresql+asyncpg://` (`app/db/session.py`).
- SQLite backup на старте пропускается для PostgreSQL.
- Backup/restore для PG — через managed layer провайдера (см. `docs/BACKUP_RESTORE_RUNBOOK.md` для SQLite).
- Чеклист cutover: `docs/POSTGRESQL_MIGRATION_CHECKLIST.md`.

## Стартовая последовательность

1. `backup_sqlite_database()` (только SQLite)
2. `alembic upgrade head`
3. Catalog/market sync
4. Uvicorn web server

Backup и offline restore: [BACKUP_RESTORE_RUNBOOK](BACKUP_RESTORE_RUNBOOK.md).
.env остаётся локальным/ignored.

Проверка перед live pilot: `python scripts/live_readiness_check.py`.

## Логи

- Text (default): стандартный формат Python logging.
- JSON: `LOG_FORMAT=json` для structured logs в production.
- Sentry: `SENTRY_DSN=` + `pip install sentry-sdk` (см. `init_error_monitoring` в `app/main.py`).

## Откат

1. Откатить deploy на предыдущую версию образа.
2. При необходимости: `alembic downgrade -1` (только если миграция обратима).
3. Проверить `GET /ready` → `200`.

## Безопасность

- Публичный доступ требует `WEB_AUTH_ENABLED=true` и HTTPS `WEB_PUBLIC_URL`.
- В dev без auth mutating `POST /api/*` требует `WEB_MANAGER_ID` либо первого настроенного admin ID.
- `/api/docs` скрыт когда auth выключен.
