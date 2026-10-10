# Включение Telegram-доставки — 2026-10-10

## Результат

По явному разрешению пользователя все 95 подходящих накопленных HOT-карточек
отправлены через @leadradaar_bot в существующий настроенный личный чат
администратора. Telegram подтвердил каждую отправку: в базе 95 строк SENT
с message_id. Отправка прошла в 12:28:37–12:29:12 по Ташкенту.
PENDING/PROCESSING/FAILED/UNCERTAIN отсутствуют, дубликатов lead/chat нет.
Ранее учтённых сообщений не было, исходный notification_logs был пуст.

Полный сервер повторно запущен в 12:35 после уточнения пояснений интерфейса.
Проверка в 12:36 и последующие циклы сохранили те же 95 записей и receipts.
При перезапуске очередь не пересылает уже доставленные карточки.

## Почему раньше не работало

1. Запуск был web-only: сайт работал с NullLeadNotifier, без Telegram polling
   и фоновой обработки очереди.
2. TELEGRAM_MANAGER_CHAT_IDS был пуст. Наличие администратора и валидного
   токена само по себе не делает администратора получателем лидов.

Перед включением проверены bot getMe/getChat/getWebhookInfo: правильный бот,
доступный личный чат, webhook не установлен, pending updates отсутствуют.
Тестовых сообщений не отправляли; первым результатом стали реальные HOT.
Сообщения Instagram-пользователям не отправлялись.

## Изменения

- TELEGRAM_NOTIFICATION_CHAT_IDS задаёт получателей независимо от ролей.
  Разрешены только существующие администраторы/менеджеры; viewer и неизвестный
  получатель отклоняются. Пустой список сохраняет прежний manager default.
- Нотификатор, web readiness и проверки настройки используют одну эффективную
  настройку получателей. Роли admin/manager/viewer остаются непересекающимися.
- WINDOWS_RUNTIME_MODE сохраняет full/web-only для Windows launcher,
  Cloudflare и существующего автозапуска. Явный web-only bat остаётся запуском
  только сайта. Скрипт не заменяет работающий процесс при смене режима молча.
- Проверка владельца процесса распознаёт полный и web-only запуск app.main;
  --once, посторонние модули и дополнительные неизвестные аргументы не подходят.
- Свежесть проверяется при постановке HOT, восстановлении очереди и доставке:
  baseline и сигналы старше настроенных 30 дней не отправляются.
- Сохранены DB outbox/unique lead-chat/idempotency key, commit до Telegram,
  сохранение message_id после ответа, retry подтверждённых ошибок и ручная
  сверка неоднозначного результата без автоматического дубля.
- Readiness поясняет статус «Не лид» независимо от старого высокого балла.
  Интерфейс показывает активного обработчика и получателя. Счётчики preview
  относятся к последним 10 сигналам, не ко всем отправкам.

Локальный `.env` настроен на full/HOT_ONLY и одного уже разрешённого
администратора. Его ID, токен и пароль в исходники не добавлены.
MONITOR_SCHEDULE_ENABLED=false, AI_PENDING_RETRY_ENABLED=false,
quality report выключен; поиск и расходы сами не запускались.

## Проверки

Перед включением создана SQLite-копия
`.backups/lead_radar-20261010-072735-telegram-activation.db`, integrity/FK PASS.
Локальная копия `.env` и якорь проверки сохранены в игнорируемой `.runtime`.

| Проверка | Подтверждённый результат |
| --- | --- |
| Накопленный backlog | 95 eligible, 95 SENT, у каждого message_id |
| Получатели | Все отправки только разрешённому получателю |
| Идемпотентность | 0 дублей; повторный полный запуск не добавил отправок |
| История и CRM | Все 839 contact_events, score/status/assignment лидов неизменны |
| Платный учёт | SHA256 external_usage, cost_events, ai_requests, external_budget_reservations, monitor_runs, provider_credit_snapshots совпадают |
| Данные | Из счётчиков всех таблиц изменился только notification_logs: 0 → 95 |
| SQLite | integrity ok, foreign_key_check пуст |
| Runtime | build 2026-10-10-telegram1, worker 5492, full, RUNNING/SERVING |
| HTTP локально/Cloudflare | health/ready/HOT/radar/system/scan preview 200, login 200, anonymous feed 401 |
| Telegram preview | token configured, recipient 1, worker active, delivery allowed |

Туннель 20564 оставлен работающим, текущая ссылка:
https://usa-hand-cooler-castle.trycloudflare.com.

Автотесты без реальных Telegram/provider отправок:

- 129 passed, 124,39 с: activation, notifications, readiness, Windows runtime,
  main/config, live/deployment readiness, workflow/analysis/pending/HOT results.
- 13 passed, 8,25 с после добавления отдельной регрессии для «Не лид».
- 33 passed, 8,32 с: web theme и структура страниц после окончательных подписей.
- Добавлен 21 случай: 10 activation, 10 Windows, 1 readiness.
- Ruff и git diff check PASS.

129 и 13 частично пересекаются; их нельзя складывать как число уникальных
тестов. Полный pytest всего проекта после этих изменений не выполнялся.
Предыдущие 1224 passed / 2 skipped относятся к прежнему этапу HOT.

Локальные доказательства: `.runtime/telegram-activation-anchor-20261010.json`,
`.runtime/telegram-activation-verified-20261010.json`,
`.runtime/telegram-stage-regressions-20261010.log`,
`.runtime/telegram-ui-regressions-20261010.log`,
`.runtime/screenshots/telegram-enabled-20261010.png`.

## Ограничения и следующий этап

Новые HOT отправляются автоматически после появления/классификации в базе
при работающем полном сервере. Instagram-поиск остаётся ручным, выбранный
предел — 5 кредитов. Резерв 235 для get_comment_batch остаётся UNCERTAIN и
блокирует новый поиск до сверки факта списания. На этом этапе резерв не
разрешали и платных API-запросов не выполняли.

9 AI_PENDING, отсутствие активных источников ротанга, полнота replies,
точность старых оценок/товарных соответствий и постоянный хостинг остаются
отдельными задачами. Temporary Cloudflare URL зависит от работающего
компьютера/соединения и может смениться при новом запуске туннеля.
