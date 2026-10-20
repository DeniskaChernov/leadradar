# Railway Deployment

Подготовленные файлы позволяют развернуть Lead Radar на Railway через
Dockerfile (`railway.json`). Развёртывание не выполнялось: платный тариф
пользователь отклонил. Текущий адрес описан в [FREE_ADDRESS.md](FREE_ADDRESS.md).

## Подготовка постоянного адреса — 2026-10-20

Выбран адрес хостинга без покупки собственного домена: Railway предоставляет
`*.up.railway.app` с HTTPS. Фактический hostname пока **не создан**.
CLI авторизован в workspace `deniskachernov's Projects`, но создание отдельного
проекта `lead-radar` 20 октября заблокировано ответом Railway:
`Your trial has expired. Please select a plan to continue using Railway.`
Новый проект/сервис/volume не созданы, код, база и секреты на Railway не отправлены.

Hobby стоит минимум $5 в месяц и включает $5 ресурсов; использование сверх этой
суммы оплачивается отдельно. Это тариф workspace, где есть другие проекты.
Общий лимит расходов workspace нельзя менять ради одного Lead Radar без отдельного
решения: он затрагивает остальные приложения. Пользователь отклонил платный
тариф; запуск Railway не планируется. Текущий постоянный адрес настроен через
[Cloudflare gateway](FREE_ADDRESS.md). Бесплатный Render не выбран: он засыпает и
не поддерживает persistent disk для SQLite.

Источники: [Railway pricing](https://railway.com/pricing),
[Railway domains](https://docs.railway.com/networking/public-networking),
[Railway volumes](https://docs.railway.com/volumes/reference),
[Render Free](https://render.com/docs/free).

### Подготовленные параметры

- Сначала staging: обычный `/railway.json` запускает `--web-only`, без второго
  Telegram polling. Healthcheck timeout увеличен с 30 до 180 секунд: локальный
  запуск с восстановлением индексов уже занимал больше 30 секунд.
- После проверки переноса выбрать `/railway.full.json` в Config File Path
  сервиса. Этот отдельный профиль запускает полный runtime и одну replica.
  Профиль сам не создаёт диск, не переносит данные и не выключает старый процесс.
- Persistent volume `/data`; `DATABASE_URL=sqlite+aiosqlite:////data/lead_radar.db`.
  База, `.backups` и runtime receipt должны оставаться на этом диске.
  Не использовать пустую SQLite внутри контейнера вместо пользовательской базы.
- Публичный порт 8000, `WEB_HOST=0.0.0.0`, вход по существующему паролю,
  `WEB_PUBLIC_URL` равен реально выданному Railway HTTPS origin.
- Безопасный шаблон: [railway.env.example](../deploy/railway.env.example).
  В нём выключены платные вызовы и расписание. Секретов в шаблоне нет.

### Перенос после разрешения расходов

1. Создать отдельный проект/пустой сервис, persistent volume и выдать домен.
   Не подключать репозиторий с autodeploy до настройки хранения и безопасных vars.
2. Сохранить актуальный SQLite snapshot через backup API, проверить integrity/FK,
   исходные ID и hash всей прежней истории `contact_events`. Перед финальным
   переключением остановить поиск/AI и зафиксировать свежую копию: подготовительная
   копия не заменяет данные, появившиеся после её создания.
3. Загрузить snapshot в volume (CLI поддерживает `railway volume files upload`).
   Через Railway Variables перенести существующие роли/пароль и нужные credentials
   без вывода значений в логи. `.env` и БД не входят в Docker build/source archive.
4. Развернуть web-only с kill switch, проверить `/ready`, закрытые маршруты,
   счётчики и историю на реальном адресе. Не запускать поиск/GPT/уведомления
   для проверки адреса. На staging не работать с лидами параллельно старому серверу.
5. Перед full cutover остановить прежний full runtime и его автозапуск Windows,
   убедиться в актуальности snapshot; затем выбрать full профиль и восстановить
   прежние live-настройки. Сохранить ручной запуск поиска и существующего бота.
   Два экземпляра polling одного токена одновременно не запускаются.
6. Проверить полный runtime, Telegram worker, auth, поиск preview и сохранность
   базы после redeploy. Лишь после этого объявлять перенос завершённым и
   закрывать временный Cloudflare. При откате сначала остановить облачный full
   runtime; не поднимать локальную устаревшую копию поверх новых облачных данных.

Увеличение timeout и подготовка профиля не означают, что deployment проверен
на Railway. Живой build, загрузка БД, переключение и проверка сохранности volume
после redeploy пока не выполнялись.

Проверки подготовки: 5 deployment readiness тестов PASS (31.51 s), Ruff/diff
check PASS. Шаблон vars проверен реальным Settings без внешних запросов:
аутентификация включена, оба платных провайдера выключены, расписание и
AI retry выключены, путь SQLite указывает в `/data`. Оба JSON профиля прочитаны;
поля deploy сверены с опубликованной Railway schema. Это не живой deployment.
Локальный Docker build не выполнялся: Docker CLI на этом компьютере отсутствует.
Снимок `.backups/lead_radar-railway-preparation-20261020-071444.db`: integrity ok,
FK 0, 558 comments/leads, 486 contacts, 2525 contact_events; исходный hash истории
из аудита совпал. Манифесты и JUnit находятся в `.runtime/railway-*20261020.*`.

## Конфигурация

| Файл | Назначение |
|------|------------|
| `railway.json` | staging/web-only, healthcheck 180 s |
| `railway.full.json` | полный runtime, одна replica; выбор после cutover |
| `Dockerfile` | Python 3.12-slim, `--web-only` |
| `docs/DEPLOYMENT.md` | env vars, security |

## Build & Start

```json
{
  "build": { "builder": "DOCKERFILE" },
  "deploy": {
    "startCommand": "python -m app.main --web-only",
    "healthcheckPath": "/ready",
    "healthcheckTimeout": 180
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
