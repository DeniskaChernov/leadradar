# Lead Radar V4.1 — Phase 0 audit report

Дата аудита: 2026-08-27  
Основание: `LEAD_RADAR_V4_MASTER_TZ_CODEX.md` и `CODEX_START_PROMPT_LEAD_RADAR_V4.txt` из Downloads.  
Режим: только офлайн-аудит. Instagram, OpenAI и Telegram API не вызывались.

## Резюме

Текущий проект — работоспособная локальная система с Signal First, CRM, Telegram outbox,
аудиториями, значимыми изменениями, replay-режимом и защитой бюджета. Подтверждённых
аварийных P0-багов в текущем однопроцессном локальном режиме не найдено.

Главный разрыв с V4 — модель данных всё ещё строится вокруг связки
`Instagram comment -> Contact -> Lead`. `PublicSignal` пока не универсален, отсутствуют
`BusinessEntity`, алиасы и нормализованная доказательная модель. Новые вертикали,
Google/Meta и полноценную Audience DNA следует вводить через аддитивную миграцию.

Проверено:

- `compileall` — OK;
- `ruff check .` — OK;
- `pytest -q` — 77 passed;
- основная БД — Alembic `c93a1f7d2e40 (head)`;
- свежая временная БД — вся цепочка миграций и повторный `upgrade head` проходят;
- integrity scan — 25 контактов, 28 комментариев, 28 сигналов, 28 лидов, 0 дублей по
  действующим уникальным ключам;
- внешнее потребление во время аудита — 0.

## 1. Карта архитектуры

```text
InstagramProvider adapters
  -> InstagramMonitor
  -> ContactService (Competitor/Post/Contact/Comment/PublicSignal + event, commit)
  -> LeadService (ANALYZING shell, commit -> rules/OpenAI/cache -> analysis, commit)
  -> AudienceEngine -> SignificantChangeDetector
  -> TelegramLeadNotifier (durable outbox -> manager)

FastAPI/Jinja web
  -> WebQueryService (read models)
  -> LeadWorkflowService / CRMService (commands + contact_events)
  -> MonitorController (manual/scheduled in-process cycle)

SQLite + SQLAlchemy async + Alembic
  -> immutable contact_events
  -> external_usage / analysis_cache / monitor_runs
```

Границы в целом соблюдены: Telegram handlers не обращаются к провайдерам напрямую,
провайдеры изолированы интерфейсом, бизнес-правила находятся в сервисах, запись сигнала
фиксируется до уведомления.

## 2. Что переиспользовать

- `InstagramProvider`, HTTP retry и fail-closed budget wrapper.
- Replay/mock сценарии и общий per-scan budget для primary/fallback.
- `ContactService` как транзакционную точку ingestion, расширив universal signal writer.
- Signal First: сохранять raw signal и outbox до внешнего анализа.
- `LeadService`, rule-first hybrid AI, structured output и `AnalysisCache`.
- `ContactEvent` как неизменяемую историю.
- Атомарные `UPDATE ... WHERE status=... RETURNING` для назначения и outbox claim.
- `AudienceEngine` и `SignificantChangeDetector` как фасады после перевода на evidence model.
- FastAPI/Jinja и существующую light liquid-glass оболочку; SPA rewrite не нужен.
- CRM, задачи, сделки, роли менеджеров, RU/UZ и cost guards.

## 3. Critical bugs

Подтверждённых Critical/P0-дефектов в текущей конфигурации нет. Система не готова к
публичному multi-worker deployment: web auth по умолчанию выключена, SQLite и блокировки
рассчитаны на локальный процесс. Это ограничение развёртывания, не авария локального режима.

## 4. High bugs и blockers

### H1. Ошибочное объединение личности

`ContactRepository.find()` ищет `platform_user_id OR normalized_username`. Если Instagram
username перейдёт другому user id, новый человек может быть объединён со старым контактом.
Нужно сначала доверять стабильному platform user id, отдельно обрабатывать смену username,
а конфликт aliases сохранять для review, не выполнять silent merge.

### H2. V4 identity и signal foundation отсутствуют

`PublicSignal` уникален только по `comment_id` и требует `Contact`/`Competitor`; в нём нет
platform/signal type/external id/canonical key/source URL/subject/evidence linkage. Нет
`BusinessEntity` и `BusinessAlias`. Это блокирует корректное подключение Google, Meta,
followers и нескольких вертикалей без дублей.

### H3. N+1 в competitor analytics

Список конкурентов выполняет пакет статистических запросов для каждого конкурента, а detail —
отдельный count для каждого поста. При расширении каталога это увеличит latency и SQLite
contention. Нужны агрегирующие subquery/CTE и bounded lists.

### H4. Distributed idempotency не доказана

`MonitorController` защищает только один процесс. Outbox claim атомарен в одной БД, но нет
lease timeout/recovery для зависшего `PROCESSING`; get-or-create repositories не везде имеют
конфликтный retry. Перед несколькими workers нужны durable run lease, stale-claim recovery и
конкурентные тесты.

### H5. Web deployment boundary легко неверно настроить

`WEB_AUTH_ENABLED=false` безопасен только с loopback bind. Нет fail-fast правила,
запрещающего `0.0.0.0`/public URL без auth/TLS. Перед публикацией нужны security headers и
явная CSRF/Origin policy для mutation routes.

## 5. Medium и minor issues

- `app.css` содержит старый dark layer и последующий light override; каскад трудно поддерживать.
- Много подписей 9–11 px, ниже целевого минимума 12 px.
- Lucide и Telegram WebApp загружаются с внешних CDN без CSP/SRI/local fallback.
- Мобильная навигация длинная; нужен приоритетный набор и «Ещё».
- При Ctrl+C aiogram может записать сетевой ERROR перед штатным shutdown.
- `ARCHITECTURE.md` и `ROADMAP.md` описывают V3.2/7 stages и расходятся с кодом/Master TZ.
- `init_database(create_all)` рядом с Alembic создаёт риск schema drift при случайном вызове.
- Integrity script не проверяет orphan FK, диапазоны score и зависшие outbox rows.
- Raw provider payload хранится без формальной retention/redaction policy.

## 6. Риски целостности данных

- Нет universal key `(platform, signal_type, external_id)` и canonical hash fallback.
- Username одновременно mutable display identity и уникальный ключ.
- Score/confidence не защищены DB CHECK 0..100.
- Taxonomy частично хранится строками/JSON без версионирования.
- `ContactIntelligence` не ссылается на evidence ids.
- `MarketCandidate.display_name` не заменяет нормализованные aliases/handles/places.
- Nullable unique в SQLite имеет отличающуюся от других СУБД семантику.
- Нужны backfill ledger/checkpoints, чтобы restart не создавал сущности.

## 7. Race conditions

- Concurrent upsert Contact/Post/Competitor может столкнуться с unique constraint; верхний
  retry ContactService спасает только появление того же comment id.
- Два разных комментария одного нового автора могут одновременно конфликтовать на Contact.
- `retry_pending` выбирает лиды до claim; два worker могут параллельно вызвать AI.
- In-process monitor lock не защищает от второго процесса.
- Outbox `PROCESSING` не имеет lease owner/expiry; crash после claim оставит запись, а crash
  после Telegram send до DB commit создаёт delivery ambiguity.
- Audience recalculation и analysis могут конкурировать за агрегат контакта.

## 8. Provider и cost risks

Сильные стороны: live требует двух switches, budget резервируется до запроса, fallback
использует общий scan budget, pagination bounded, replay не расходует токены.

Оставшиеся риски:

- daily usage check и subsequent record не являются одной atomic reservation;
- отсутствует durable request ledger/idempotency key для crash retries;
- единица стоимости не равна реальной цене provider dataset/job;
- Bright Data asynchronous job/polling требует отдельной cost state machine;
- перед live интеграцией нужен preview calls/cost/freshness/coverage;
- scheduled live scan нельзя включать до durable leases и cost reservation.

## 9. Security и auth

Положительно: Telegram initData проверяется HMAC и age, admin allowlist поддерживается,
cookie HttpOnly/SameSite=Strict, secure для HTTPS, Jinja autoescape и Telegram escaping
используются, секреты берутся из `.env`.

До публичного доступа нужны:

- fail-fast: non-loopback bind запрещён без auth, HTTPS и admin allowlist;
- CSP, frame-ancestors, nosniff, referrer и permissions policy;
- Origin/CSRF protection mutation endpoints;
- rate limit auth/scan/mutations и body size limits;
- rotating session secret вместо производного от bot token/local constant;
- revocation/key rotation и retention/redaction policy.

## 10. Telegram Mini App

Рабочее: allowlist, live-scan confirmation, outbox, retries, manager routing, escaping,
idempotent callbacks, enrichment edit/fallback.

Разрывы: нет stale claim recovery, delivery reconciliation, end-to-end auth tests, Telegram
message/callback limit tests и локального fallback Telegram JS. Действия должны продолжать
идти только через сервисы и `contact_events`.

## 11. UI/UX

Сохраняем текущую light liquid-glass тему: это более новое подтверждённое решение пользователя,
хотя отдельный раздел Master TZ упоминает dark navy.

Приоритеты:

1. консолидировать CSS tokens/layers без визуального изменения;
2. единые header/filter/table/card/detail patterns;
3. минимум 12 px secondary text и 44 px touch targets;
4. mobile nav: ключевые разделы + «Ещё»;
5. компактные score factors/evidence/confidence/next action;
6. loading/empty/error/partial/stale/offline states;
7. pagination/virtualization больших списков;
8. Vertical filter после Phase 1.

## 12. Accessibility

Уже есть skip link, semantic nav, `aria-current`, focus-visible и reduced-motion tests.
Нужны WCAG contrast check, keyboard modal focus trap/restore, live-region errors, labels всех
форм, axe scan и viewport matrix 360/390/768/1024/1440 px.

## 13. Migration plan

Phase 1 — только аддитивная:

1. добавить `Vertical` с `FURNITURE` default;
2. добавить `business_entities`, `business_aliases`, `signal_evidence` и nullable universal
   поля в `public_signals`;
3. unique canonical identity и CHECK constraints — после backfill validation;
4. backfill Competitor -> BusinessEntity, handle -> BusinessAlias;
5. backfill Comment/PublicSignal external identity и evidence без изменения старых IDs;
6. сохранить старые FK/reads, затем dual-read и dual-write;
7. reconcile counts/hash до переключения read path;
8. rollback отключает dual path, новые таблицы не удаляет;
9. тестировать fresh DB, копию текущей БД, repeat/restart/interruption;
10. backup + restore drill до рабочей БД.

## 14. Dead и duplicated code

- `init_database(create_all)` — кандидат на удаление/перенос в test helper.
- `LeadWorkflowService` и `CRMService` частично дублируют transition/assignment/deal rules.
- В CSS дублируются dark base и light override.
- V3.2 architecture/roadmap — устаревшая документация.
- Два LeadService assembly path допустимы по cost policy, но wiring лучше вынести в factory с
  явным `NetworkPolicy`.

## 15. Недостающие тесты

- username reassignment/user id conflict/alias merge-split;
- concurrent ingestion одного contact/post/signal;
- two-worker AI claim, monitor lease и stale outbox recovery;
- crash after send/before commit и provider call/before usage record;
- orphan/FK/status/score integrity и migration interruption;
- auth denial/public bind/CSRF/headers/cookie rotation;
- malformed cursor/429 retry storm/asynchronous jobs;
- query budgets на 100/1,000 competitors;
- full viewport/a11y/keyboard/contrast matrix;
- multi-vertical isolation/universal dedupe/evidence provenance;
- Google/Meta policy gates и external usage == 0.

## 16. Implementation plan (Phases 1–12)

### Phase 1 — Data foundation

Vertical, BusinessEntity/Alias, universal PublicSignal, evidence и safe backfill. Риск: неверный
merge. Acceptance: counts reconcile, repeat gives zero rows, old pages/tests green, zero calls.

### Phase 2 — Real-time notification hardening

Durable leases, stale recovery, idempotency keys, delivery ambiguity и SLA. Acceptance:
two-worker/crash tests доказывают one claim и явное uncertain-delivery state.

### Phase 3 — Intelligence V2

Versioned factors, confidence, evidence ids, role scores. Acceptance: golden dataset,
calibration и каждый score связан с evidence; rule-first default.

### Phase 4 — Profile and Audience DNA

Evidence-backed profile, person/business segments и similarity. Acceptance: no private traits,
expiry/provenance visible, deterministic replay.

### Phase 5 — Vertical UI

Vertical context во всех основных views. Acceptance: responsive/a11y matrix и no leakage.

### Phase 6 — Rattan intelligence

Furniture/rattan taxonomy, quantity/HoReCa evidence. Acceptance: RU/UZ fixtures и precision
guardrails.

### Phase 7 — Competitor demand gap

Batched analytics, overlap, unanswered observable demand и coverage labels. Acceptance: bounded
query budget и отсутствие ложного вывода «нет ответа» из «ответ не наблюдаем».

### Phase 8 — Followers

Только разрешённые public follower signals. Acceptance: policy gate, cost preview, retention,
disabled by default, no private/hidden data.

### Phase 9 — Meta catalog/recipes

First-party eligible audiences/recipes и catalog mapping. Acceptance: eligibility evidence,
dry-run, audit log, no export by default.

### Phase 10 — Google future openings

Business/place entities и opening signals. Acceptance: place resolution, source/date/coverage,
confidence и review queue.

### Phase 11 — UI refinement

Consolidated liquid-glass system, states, a11y/performance. Acceptance: screenshot matrix,
axe/keyboard pass, no horizontal overflow.

### Phase 12 — Hardening

Load/race/security/backup-restore/observability runbooks. Acceptance: all quality gates,
zero external calls in tests и recovery drills.

## 17. Что не переписывать

- не заменять FastAPI/Jinja новым SPA;
- не менять SQLite без подтверждённой multi-process/load потребности;
- не удалять старые tables/FK в Phase 1;
- не переписывать adapters, replay и budget guards;
- не обходить services из Telegram/web handlers;
- не заменять `contact_events` mutable history;
- не включать live APIs/scheduled search/AI в тестах;
- не менять light theme без явного решения пользователя;
- не строить скрытые профили и не собирать private Instagram data, phone/email.

## Решение Phase 0

Phase 0 завершена. Следующее разрешённое действие — Phase 1 (data foundation) после явного
подтверждения владельца. До подтверждения feature code и миграции V4 не создаются.
