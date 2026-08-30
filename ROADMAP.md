# Lead Radar — дорожная карта

Lead Radar строится не как «парсер комментариев», а как система, которая последовательно отвечает
на три вопроса: **где появился спрос → кто с наибольшей вероятностью купит → что ему предложить,
чтобы довести до сделки**.

## Стадия 1. Надёжный фундамент данных — ГОТОВО

- единая база Contacts / Signals / Leads / Deals;
- дедупликация и idempotency;
- история действий ContactEvent;
- truthful coverage комментариев;
- fallback providers;
- миграции, integrity checks и replay tests.

## Стадия 2. Mini App + CRM продаж — ГОТОВО

- русскоязычный Mini App;
- Radar, Leads, Contacts, Tasks, Deals, Analytics;
- карточка клиента 360°;
- Telegram HOT alerts;
- локальный RU/UZ классификатор;
- safe/replay разработка без внешних токенов;
- double unlock и бюджеты live API.

## Завершённый фундамент

- встроенная карта подтверждённых конкурентов;
- отдельный реестр market candidates;
- сегменты DIRECT / DINING / OUTDOOR / HORECA / PREMIUM / MASS;
- Tier A/B/C;
- новые аккаунты добавляются на паузе, чтобы не увеличивать расходы автоматически;
- эффективность источника: сигналы, HOT, продажи, выручка, HOT-rate;
- повторный интерес у нескольких конкурентов повышает приоритет человека;
- рекомендации «усилить / оставить / фоновый / набираем данные».

Также реализованы offline: evidence-first Lead Scoring V3, Audience Intelligence V4.1,
искусственный ротанг V2, durable Telegram outbox, budget/cost ledger, Discovery Center,
подтверждаемый каталог, grounded Next Best Action и 600-case robustness replay.

Это не означает live/production readiness: независимые quality gates и controlled live pilot
ещё не пройдены.

## Master work order 2026-08-31

- Phase 1 Remaining P0 correctness — **ГОТОВО**;
- Phase 2 Radar Credit Budget — **В РАБОТЕ**;
- Phase 3 Adaptive Monitoring — далее;
- Phase 4 Economics — далее;
- Phase 5 Audience correctness — далее;
- Phase 6 Independent quality gates — далее;
- Phase 7 Grounded Agent — далее;
- Phase 8 UI final hardening — далее;
- Phase 9 Deployment — далее;
- Phase 10 Controlled live pilot — только по отдельному разрешению.

## Активная программа завершения

### Stage 0. Truth и baseline — ГОТОВО

- единое актуальное состояние в `State.md`, `PROJECT_STATUS.md` и этой дорожной карте;
- проверяемая резервная копия рабочей БД;
- зафиксированные offline quality gates и честные блокировки live.

### Stage 1. Schema contract — ГОТОВО

- устранить drift ORM/Alembic для Product и Meta foundation;
- сохранить все существующие данные;
- проверить fresh/existing/repeated migration и `alembic check`;
- сделать schema check обязательным в CI.

### Stage 2. Production security boundary — ГОТОВО

- fail-closed при публичном запуске без auth;
- Telegram initData/session, CSRF/origin protection;
- роли viewer/manager/admin и авторизация mutating/system endpoints;
- security regression tests без внешней сети.

### Stage 3. Workflow integrity — ГОТОВО

- единый порядок DB transaction → immutable event → commit → outbox;
- идемпотентность HTTP/Telegram повторов;
- race tests для CRM, discovery, catalog и moderation;
- расширенный integrity scan.

### Stage 4. Catalog → Offer → Demand Gap — ГОТОВО

- versioned manager-confirmed свойства каталога и импорт с dry-run/diff;
- объяснимое ранжирование предложений по Evidence;
- связь WON deal с Product и immutable sale snapshot;
- наблюдаемый спрос против подтверждённого покрытия каталога;
- без домыслов о Direct или скрытых ответах конкурента.

### Stage 5. Unit Economics — ГОТОВО

- подтверждённый COGS проданного товара;
- cohort attribution;
- versioned FX policy;
- margin/ROI только при полном наборе фактов.

### Stage 6. Independent quality gates — ЗАПЛАНИРОВАНО ПОСЛЕ MASTER PHASE 5

- 100+ независимо размеченных audience membership cases;
- отдельные calibration/challenge/robustness/unseen наборы;
- importer для 500–1000 архивных публичных сигналов;
- воспроизводимые precision/recall/confusion отчёты.

### Stage 7. Grounded Agent/MCP

- существующий typed gateway подключается к реальным DB services;
- read tools возвращают Evidence-backed факты;
- write tools используют durable human approval и idempotency;
- AI расходы проходят через существующий ledger/reservation;
- Meta/spend tools закрыты до реального adapter contract.

### Stage 8. UI и Telegram offline hardening

- truthful состояния всех экранов;
- desktop/mobile/accessibility/browser regression;
- dry-run/race/retry/UNCERTAIN для Telegram;
- реальная доставка остаётся отдельным pilot gate.

### Stage 9. Deployment readiness

- PostgreSQL compatibility;
- health/readiness, graceful shutdown и structured logs;
- backup/restore drill;
- fail-closed live preflight;
- SQLite + PostgreSQL CI matrix.

### Stage 10. Controlled live integrations — ТОЛЬКО ПО ОТДЕЛЬНОМУ РАЗРЕШЕНИЮ

- один выбранный Instagram provider с минимальным ручным лимитом;
- отдельный Telegram manager chat;
- OpenAI только через budget ledger;
- Meta/Google только через официальные adapters, credentials, privacy и budget gates;
- после пилота — reconciliation и повторное отключение live.

До Stage 10 любые Instagram/OpenAI/Telegram delivery/Meta/Google live-вызовы запрещены.

## Что должно увеличивать количество лидов

1. Больше качественных источников, а не просто больше API-вызовов.
2. Поиск открытого спроса вне страниц конкурентов.
3. Повторный пользователь у нескольких продавцов как усиленный сигнал.
4. Отдельный B2B/HoReCa скоринг.
5. Быстрая реакция менеджера и задачи follow-up.
6. Каталог наших товаров и мгновенный релевантный оффер.
7. Возврат старых клиентов при новом сигнале.
8. Анализ причины проигрыша и перераспределение внимания на источники, которые дают продажи.
