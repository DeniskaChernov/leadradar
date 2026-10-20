# Размещение Lead Radar на Render Free и Neon Free

## Выбранный режим

Пользователь согласовал бесплатное размещение без банковской карты и запуск
при открытии кабинета. После 15 минут без входящего трафика Render Free
останавливает процесс; пробуждение занимает примерно минуту. Во сне Telegram
polling и обработка команд недоступны. Искусственный keepalive не настраивается.
Локальный диск Render эфемерен, поэтому SQLite на него не переносится.
Не использовать Render Free Postgres с истечением через 30 дней.

Внешняя база — отдельный Neon project lead-radar, регион Frankfurt,
PostgreSQL 18, план существующей организации Free проверен. Ограничения Free
на дату проверки: 1 GB/project, 100 CU-hours/month/project. Не добавлять карту,
не переходить на paid plan и не создавать платные диски/фоновые workers.
Oracle, Railway и Northflank исключены по условиям пользователя.

Приложение ещё работает на компьютере. Перенос не завершён: вход в Render
не выполнен, владелец сообщил, что не получается войти. Source worktree с
подготовкой отделён от live worktree, чтобы новая head не ломала старый /ready.

## Подготовка базы

Neon project: young-haze-35624501. Production branch br-morning-pine-b9lklzht
пока без таблиц. Изолированные child branches:
- migration-staging / br-empty-cake-b9jpfpqi — исторические Alembic миграции;
- snapshot-validation / br-blue-silence-b9e8fxbs — восстановление полной копии.

Существующий BTT CRM project не затрагивается. Предварительная исходная копия:
.backups/lead_radar-server-migration-20261020-082954.db в live worktree,
SHA256 0b97da3b938656e9b405114c279f6c5956d13ba4943e2183ae183b43956f450d.
Это предварительная копия, не финальная production база.
558 comments/leads, 486 contacts, 2525 contact_events, 711 cost_events,
152 SENT lead notifications и 3 SENT significant-change notifications.
Integrity ok, FK violations 0. Оригинальная revision ca219b748d30.

Создать рабочую копию через штатный SQLite backup, обновить только её до head.
Новая revision d72c4a9e1036 расширяет 15 колонок Telegram IDs до BIGINT на
PostgreSQL. В SQLite это no-op, кроме Alembic version. Контрольные суммы
всех 53 таблиц должны совпасть до/после обновления. Следующая revision
e83d5baf2147 расширяет language в PostgreSQL до TEXT, сохраняя длинные
исторические метки без обрезания. SQLite VARCHAR(16) остаётся прежним.

DSN брать из Connect для нужного branch и роли, не из другого проекта.
Для asyncpg сформировать driver-native URL postgresql+asyncpg с direct endpoint
(без -pooler) и ssl=verify-full. Не передавать libpq параметр channel_binding
драйверу asyncpg. DSN хранить только в отдельном игнорируемом .runtime env file.
Системные CA, CERT_REQUIRED и hostname verification обязательны.

## Проверяемое восстановление

Dry run читает SQLite в read-only транзакции и не подключается к цели:

    python -m scripts.migrate_sqlite_to_postgres --snapshot .runtime/migration-source.db

Для полного восстановления нужна БД **без таблиц**. Исторические Alembic
миграции создают стартовые policy rows, поэтому сначала выполнять их на такой
цели нельзя. Явный флаг создаёт текущую схему из моделей и version row внутри
той же PostgreSQL транзакции, что и импорт. Snapshot revision должна совпадать
с единственной head кода. Никакая существующая схема не очищается.

    python -m scripts.migrate_sqlite_to_postgres --snapshot .runtime/migration-source.db --env-file .runtime/neon-target.env --apply --initialize-target --report .runtime/import.json

Повтор после успешного импорта — без --initialize-target:

    python -m scripts.migrate_sqlite_to_postgres --snapshot .runtime/migration-source.db --env-file .runtime/neon-target.env --apply --report .runtime/import-repeat.json

Повтор должен вернуть copied=false, sequences_repaired=0 и те же 53 хеша.
Отличающаяся непустая база, несовпадение revision или неожиданные таблицы —
отказ, без удаления/перезаписи. Проверить command.check и реальные страницы.
Платные API и Telegram сообщения ради проверки не запускать.

## Первоначальный Render staging

render.yaml — JSON-совместимый YAML. Один service Free, Frankfurt, Docker,
ветка codex/render-neon-migration, autoDeployTrigger=off. Health check:
/health/runtime, один запрос revision с лимитом 3 секунды. Полный аудит /ready
с Alembic reflection остаётся ручной проверкой и не подходит для probes каждые
несколько секунд: Render ждёт HTTP ответ не более 5 секунд. Нет Render database,
диска, cron или отдельного worker. Command: python -m app.main --web-only.
Вход через GitHub DeniskaChernov завершает владелец. До создания проверить,
что UI действительно показывает Free и не требует карту/оплату.

Приватно задать в Render Environment DATABASE_URL нужного staging branch,
текущий WEB_PASSWORD_HASH, TELEGRAM_ADMIN_CHAT_IDS и фактический HTTPS WEB_PUBLIC_URL выделенного
onrender.com адреса. Не отключать CSRF, TrustedHost или обязательный вход.
Не загружать .env в Git/Docker image. Bot token на staging не передаётся.
Render генерирует отдельный WEB_SESSION_SECRET для подписи сессий/CSRF;
он должен оставаться постоянным при перезапуске контейнера. Минимум 32 символа.
Ротация этого ключа или смена пароля отзывают существующие веб-сессии.
Kill switch включён, live unlock пустой, провайдер replay; live Instagram/OpenAI,
поиск, расписание и retries отключены. Replay поиск на импортированных данных
тоже не запускать: он создаст fixture данные.

Проверить /health, /ready, отказ без входа, HOT, карточки, searches, группировку
по постам/компаниям, историю и бесплатные preview. Проверить повторный запуск
с сохранением PostgreSQL данных. Не считать web-only готовым full bot.

## Что требуется перед полным переключением

1. Проверить единственное владение full runtime на PostgreSQL. Текущий
   DatabaseRuntimeLock защищает SQLite файлом; PostgreSQL не даёт exclusive=true,
   поэтому recovery прерванных поисков там намеренно пропускается. Render rollout
   может временно держать старый и новый экземпляры. До устранения/проверки
   этого ограничения full polling и автоматический redeploy не включать.
2. Проверить отсутствие активного поиска/анализа локально. Сохранить настройки
   Windows автозапуска, отключить локальный bootstrap и gateway watchdog,
   остановить локальный full runtime. Только затем снять свежую финальную копию.
3. Обновить копию до head, восстановить в пустой production branch, сравнить
   все таблицы и историю. Staging-копия не заменяет свежую финальную.
4. Приватно передать прежние настройки бота/ролей, пароль и лимиты поиска
   в Render Environment. Сохранить ручной режим и существующего бота.
5. Запустить один full runtime; проверить readiness и отсутствие второго polling,
   страницы без платных поисков и тестовых Telegram отправок.
6. Переключить публичный URL. Имеющийся Cloudflare Worker принимает только
   trycloudflare origin; нельзя записать туда onrender.com и объявить работу
   проверенной. Для старой ссылки нужен безопасный redirect alias, либо
   использовать постоянный URL Render. Это ещё не сделано.
7. Проверить остановку/пробуждение Render, отсутствие дублей и сохранность данных.
   Только после этого объявлять приложение независимым от ПК.

Rollback: сначала остановить удалённый full runtime. Если на сервере уже были
изменения, вернуть актуальные данные, а не предварительный SQLite snapshot.
Затем восстановить локальный автозапуск и штатный launcher. Не включать два бота.

Источники: [Render Free](https://render.com/docs/free),
[Blueprint](https://render.com/docs/blueprint-spec),
[Rollout](https://render.com/docs/deploys),
[Health checks](https://render.com/docs/health-checks), [Neon](https://neon.com/pricing),
[Connections](https://neon.com/docs/connect/connect-from-any-app),
[asyncpg](https://magicstack.github.io/asyncpg/current/api/index.html).
