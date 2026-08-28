# Lead Radar — состояние проекта

## Текущая версия

**CORE HARDENING IN PROGRESS · NOT READY FOR LIVE PILOT**

Текущая цель: доказать корректность ядра по новому Master Task. Старые заявления «100% complete»
и «Production Ready» считаются историческими и не являются доказательством готовности.

## Честная матрица готовности

| Feature | Implementation status | Test status | Live tested | Production ready |
|---|---|---|---|---|
| Audit + network freeze | Implemented | Offline automated | No | No |
| AI request/budget ledger | Phase B hardened | 186 offline tests + concurrency + migration | No | No |
| Cost ledger & pricing | OFFLINE · durable ledger/config implemented | 190 offline tests + migration | No | No |
| Lead Scoring V3 | Implemented in rule pipeline | 30 golden + component tests | No | No |
| Audience Engine V3 | Evidence-first core implemented | Unit/integration; golden expansion pending | UI offline | No |
| Rattan Vertical V2 | Evidence-first core implemented | 24 golden + integration/idempotency | UI offline | No |
| Unit Economics ledger | Not implemented | Calculator tests only | No | No |
| Premium UI / Telegram Bot | Read-only readiness + durable outbox implemented | Unit/concurrency/browser dry-run | Delivery not run | No |
| Real Agent / MCP | Prototype/mock | Fixture tests only | No | No |
| Meta / Google | Not connected | Offline prototype only | No | No |
| Offline 500–1000 signal pilot | 540-case robustness replay passed | 54 curated roots × 10 variants; unseen corpus pending | No | No |
| Controlled live pilot | Blocked | Missing gate evidence | No | No |

## Phase C — Lead Scoring V3

- реальный rule pipeline переведён на Intelligence `3.0` с отдельными component scores;
- добавлены `CommercialSignalQuality`, explainable priority и отдельный confidence;
- реакции и шум исключены из history/multi-competitor boost;
- sequence progression сильнее одинаковых повторов, повторения имеют diminishing returns;
- intent-specific decay реально используется в history и Audience activity;
- `B2BPolicy 1.0` централизует contextual/30+/50+ thresholds;
- AI fingerprint учитывает только коммерческую историю, stable contact identity, vertical и catalog context version;
- OpenAI output не может сохранить выдуманные Evidence IDs; без Evidence confidence снижается;
- текущая golden calibration содержит только 30 сценариев — pilot gate 150–300 ещё не выполнен;
- полный offline suite после Phase G: 180 тестов, внешних вызовов нет.

## Phase D — Audience Engine V3

- добавлены идемпотентные `InterestEvidence`, связанные с реальными Evidence/PublicSignal;
- `ContactInterestProfile` хранит decayed score, confidence, first/last seen, source count и Evidence IDs;
- реакции и некоммерческий шум не создают interest evidence и не усиливают multi-competitor;
- membership хранит структурированные причины, реальные Evidence IDs, expiry и engine version;
- `OutcomeDNA` использует только признаки, наблюдавшиеся до `won_at`, без leakage статуса WON;
- интерфейс сегмента показывает менеджеру «почему контакт здесь»;
- миграция `f3b9d7a61c20` применена к рабочей БД, Alembic schema check чистый;
- полная цепочка Alembic подтверждена отдельно на новой пустой SQLite БД;
- текущая рабочая БД: 16 evidence-first interest profiles, 650 уникальных memberships, дубликатов нет;
- audience golden/eval пока недостаточен, поэтому production/pilot ready остаётся `No`.

## Phase E — Artificial Rattan Vertical V2

- добавлен строгий `RattanTaxonomyService`: без явного rattan-контекста обычные столы,
  кресла и мебель остаются в вертикали `FURNITURE`;
- сырьё (`RAW_RATTAN`, бухта, кг, плоский/круглый/полукруглый профиль) отделено от
  готовой ротанговой мебели и ролей рынка;
- `vertical` проходит через Competitor, PublicSignal, Evidence, Lead и AudienceSegment;
- сохранённые записи перестраиваются идемпотентно, Evidence остаётся источником
  доказательств, а BusinessEntity получает объединение наблюдавшихся вертикалей;
- отдельный `/rattan` workspace показывает только реальные записи БД и честно сообщает,
  что источник поиска выключен; demo-компании не создаются;
- добавлены отдельные rattan-аудитории для сырья, готовой мебели, опта и высокой ценности;
- migration `a6d4e2c91f30` проверена на рабочей и новой пустой SQLite БД;
- golden fixture: 24 RU/UZ/EN сценария, включая отрицательные примеры и ложные
  совпадения по «кг», кабелю и обычной мебели;
- рабочая БД: 22 доказательных rattan-сигнала и 1 подтверждённая компания;
- integrity gate: 0 дублей и 0 вертикальных рассогласований Lead/Evidence/PublicSignal;
- полный offline gate после Phase G: 180 tests passed, Ruff, compileall и Alembic check чистые;
- live discovery и внешний pilot не запускались, поэтому production ready остаётся `No`.

## Phase F — Deterministic Offline Pilot

- добавлен network-free runner `python -m scripts.run_offline_pilot`;
- 54 вручную размеченных корневых сценария разворачиваются в 540 вариантов регистра,
  пробелов, пунктуации и emoji;
- текущий robustness replay: lead precision/recall/intent accuracy 100%, rattan
  precision/recall/layer accuracy 100%;
- первый ingestion создаёт ровно 540 Comment/PublicSignal/Evidence, идентичный повтор —
  0 новых записей и 0 дублей;
- pilot выявил и помог исправить ложные пропуски коммерческого CTA `+?`, `+!`,
  `+ 🙏`, `+...`, не ослабляя правило для плюса без явного CTA в подписи;
- результат и ограничения задокументированы в `docs/OFFLINE_PILOT_REPORT.md`;
- это robustness-набор из 54 независимых корней, а не 540 независимо собранных
  реальных примеров; unseen public-data pilot и live pilot всё ещё не пройдены.

## Phase G — Telegram Notification Readiness

- добавлен полностью read-only dry-run preview: он применяет фактическую global/per-
  competitor policy, baseline guard, HOT threshold, manager routing и состояние outbox;
- preview не создаёт NotificationLog и не вызывает Telegram API;
- интерфейс `/system` показывает ELIGIBLE/QUEUED/SENT/SUPPRESSED/BLOCKED/FAILED/
  UNCERTAIN, число получателей и стабильный шаблон idempotency key без раскрытия chat ID;
- web-only режим теперь честно показывает, что token может быть настроен, но delivery
  worker не запущен; это исключает ложный статус «уведомления работают»;
- текущий безопасный runtime: token настроен, один admin target найден, delivery config
  заблокирован, worker выключен, все 10 просмотренных лидов подавлены baseline guard;
- повторный preview детерминирован и оставляет таблицу notification_logs неизменной;
- реальная отправка менеджеру всё ещё не выполнялась и требует отдельного явного
  controlled pilot.

## Post-audit hardening — AI cost ledger

- GitHub `origin/main` сверён: локальная разработка продолжена от Phase B без конфликтов;
- добавлена отсутствовавшая миграция `e8a4c2f91b70` для `ai_requests` и
  `external_budget_reservations`;
- AI ledger теперь использует реальный `lead_id`, атомарный claim и уникальный claim token;
- два независимых AI-воркера не выполняют один контекст одновременно;
- SQLite budget reservation сериализуется между процессами через раннюю write-lock транзакцию;
- expired reservations становятся `EXPIRED`, finalize/release выполняются compare-and-set;
- `.env.example` документирует глобальный `EXTERNAL_KILL_SWITCH`;
- migration matrix, schema check, Ruff и 159 offline-тестов проходят без внешних вызовов.

## Phase B — AI idempotency and atomic budget reservations

- AI context fingerprint вынесен в отдельный сервис и версионирует contract `3.0`,
  prompt, schema и model; реакции не меняют fingerprint;
- уникальный `(lead_id, analysis_version, context_fingerprint)` и DB claim обеспечивают
  один ledger row и максимум один внешний вызов для пяти конкурентных воркеров;
- lease теперь конфигурируется (`180s`), worker ID включает host/PID, а после трёх
  оплачиваемых неудач запрос переходит в `PERMANENT_FAILURE`;
- отключённый OpenAI и отказ резервирования не расходуют счётчик оплачиваемых попыток;
- бюджет резервируется до вызова под SQLite `BEGIN IMMEDIATE`; 20 конкурентных запросов
  при лимите 10 создают не более 10 резерваций;
- каждая резервация имеет стабильный key, worker, timestamps, actuals и details, а
  `ExternalUsage.idempotency_key` защищает историю расходов от повторного finalize;
- начало внешнего вызова фиксируется отдельно: неизвестный billing после сетевого сбоя
  учитывается консервативно, а точно неотправленная stale reservation освобождается;
- startup recovery идемпотентно разбирает stale AI/budget leases; `/system` показывает
  статусы AI, активные резервации и неопределённые списания без внешних запросов;
- миграция `c7f1a8d42e90` проверена на новой БД, рабочей БД с backup и повторном upgrade;
- CI выполняет Ruff, compileall, fresh/existing/repeated Alembic и полный pytest;
- текущий offline gate: **186 passed**, Ruff и compileall чистые; live API не вызывались,
  production ready остаётся `No`.

## Master Phase A — Core money-safety completion

- прежний Instagram wrapper с паттерном `assert → API → record` упрощён до того же
  двухфазного контура `RESERVE → mark started → API → FINALIZE`, который использует OpenAI;
- `CostEvent` теперь создаётся exactly-once из завершённой budget reservation и хранит
  provider, operation, units, tokens, известную стоимость и доступную attribution;
- `PricingConfig` хранит версионированные активные тарифы; предыдущая цена деактивируется,
  но сохраняется для аудита;
- если тариф или actual cost неизвестны, стоимость хранится как `NULL`, а не как ложный `$0`;
- минимальная форма управления тарифами добавлена в `/system`, отдельная вкладка ради одной
  настройки не создавалась;
- reservation status поддерживает `UNCERTAIN`, provider теперь является явным полем ledger;
- миграция `d8e2b7c41a90` проверена на fresh/repeated upgrade; рабочая БД обновляется только
  после backup;
- полный offline gate после Master Phase A: **190 tests passed**, Ruff и compileall чистые;
- maturity: core ledger **OFFLINE**, live provider billing reconciliation **NOT LIVE TESTED**;
  controlled live pilot остаётся `BLOCKED`.

## Архив прежних заявлений V6 — требует повторной проверки по новому Master Task

- **Phase V6.0 (Audit & Security Gate)** — **ЗАВЕРШЕНО**:
  - Составлены обязательные документы аудита: `V6_PRE_IMPLEMENTATION_AUDIT.md`, `V6_SECURITY_AUDIT.md`, `V6_DATA_INTEGRITY_AUDIT.md`, `V6_UI_UX_AUDIT.md`, `V6_BOT_UX_AUDIT.md`, `V6_DESIGN_SYSTEM_AUDIT.md`.

- **Phase V6.1 (Data/Event Hardening & Runbooks)** — **ЗАВЕРШЕНО**:
  - Реализован экспоненциальный полураспад интересов `calculate_decayed_interest_score()`;
  - Создан CLI-скрипт восстановления БД `scripts/restore_database.py` и регламент `docs/BACKUP_RESTORE_RUNBOOK.md`;
  - Добавлен переключатель контекста вертикалей `[ 🪑 Мебель ] [ 🌾 Искусственный ротанг ]`;
  - Добавлен раздел и веб-страница `/openings` для модерации заведений.

- **Phase V6.3 (Intelligence V3 & EvidenceBundle Engine)** — **ЗАВЕРШЕНО**:
  - Модуль `evidence_bundle_service.py` с декомпозицией скоринга на 10 факторов.

- **Phase V6.5 (Rattan Business Role Classifier)** — **ЗАВЕРШЕНО**:
  - Сервис `rattan_classifier_service.py` для доказательной классификации ролей рынка ротанга.

- **Phase V6.6 (Competitor Intelligence V3 & Opportunity Engine)** — **ЗАВЕРШЕНО**:
  - Модуль `competitor_opportunity_service.py` с анализом коммерческой конверсии контента и поиском дыр спроса.

- **Phase V6.8 (Meta Ads Targeting Recipe Engine)** — **ЗАВЕРШЕНО**:
  - Модуль `targeting_recipe_service.py` для генерации таргетинговых рецептов (`NARROW`, `BALANCED`, `BROAD`).

- **Phase V6.9 (Google Marketing Intelligence Engine)** — **ЗАВЕРШЕНО**:
  - Модуль `google_marketing_service.py` для агрегации поисковых запросов Google Ads, Search Console и GA4.

- **Phase V6.10 (Next Best Action Engine)** — **ЗАВЕРШЕНО**:
  - Сервис `next_best_action_service.py` для генерации точных рекомендаций менеджерам со ссылками на SKU.

- **Phase V6.11 (Internal MCP Gateway & Agent Session Assistant)** — **ЗАВЕРШЕНО**:
  - Модуль `mcp_gateway_service.py` и `agent_session_service.py` с эндпоинтом `/api/agent/query` и защитой Human-in-the-Loop.

- **Phase V6.15 (Unit Economics & Cost Control Engine)** — **ЗАВЕРШЕНО**:
  - Сервис `unit_economics_service.py` для расчёта CPL, CPH, CPW и окупаемости `roi_ratio`.

- **Phase V6.16 (Full Hardening & Quality Gate)** — **ЗАВЕРШЕНО**:
  - **Pytest**: 151/151 тестов успешно пройдены (100% офлайн);
  - **Linter**: Ruff lint — 0 ошибок;
  - **Integrity**: Все 17 проверок целостности — OK.

- **Phase V6.17 (Controlled Live Pilot Preparation)** — **ЗАВЕРШЕНО**:
  - Создан предполётный скрипт готовности `scripts/live_readiness_check.py` (Возвращает `STATUS: READY FOR LIVE PILOT`);
  - Написан регламент пилотного запуска `docs/LIVE_PILOT_CHECKLIST.md`;
  - Составлена документация архитектуры MCP-инструментов и агента (`docs/V6_MCP_TOOL_MAP.md`, `docs/V6_AGENT_ARCHITECTURE.md`, `docs/V6_VISUAL_QA.md`, `docs/V6_BOT_QA.md`, `docs/INTEGRATION_DOCS_VERIFIED.md`).

## Master TZ Phase 10 — завершён







- Добавлена Alembic миграция `b1c2d3e4f5a6_opening_signals.py` и ORM-модель `OpeningSignal`;
- Создан сервис `PlaceOpeningService` (`app/services/place_opening_service.py`):
  - Детектирование сигналов открытия ресторанов, кафе, отелей, офисов и шоурумов в комментариях/публикациях;
  - Идемпотентное сохранение сигналов открытий со статусом `PENDING_REVIEW` и оценкой уверенности 50-95%;
  - Очередь модерации для менеджера с переводом в `VERIFIED` или `REJECTED`;
- Добавлены Web API эндпоинты `GET /api/openings` и `POST /api/openings/{opening_id}/review`;
- Написана группа тестов `tests/test_place_openings.py` (4/4 pass);
- 132 теста, Ruff lint и 17 integrity checks проходят на 100%.

## Master TZ Phase 9 — завершён


- Создан модуль `app/services/export_recipe_service.py` с `CatalogMapper` и `ExportRecipeService`;
- `CatalogMapper` сопоставляет 12 товарных категорий Lead Radar с иерархической таксономией Meta Custom Audiences / Google Product Taxonomy;
- Реализованы 4 зафиксированных рецепта экспорта (`b2b_horeca_wholesale`, `designers_contractors`, `high_intent_dining`, `comparison_shoppers`);
- Строгий контроль приватности: `dry_run=True` (по умолчанию) генерирует только SHA-256 хеши и счетчики допустимых контактов без раскрытия PII;
- Подтверждённый экспорт (`dry_run=False`) обрабатывает исключительно контакты в статусе `ExportEligibility.FIRST_PARTY_ELIGIBLE`, переводит статус в `EXPORTED` и создает аудируемые записи в `contact_events`;
- Добавлены Web API эндпоинты `GET /api/audiences/export-recipes` и `POST /api/audiences/export-recipes/{recipe_slug}`;
- Написана группа тестов `tests/test_export_recipes.py` (5/5 pass);
- 128 тестов, Ruff lint и 17 integrity checks проходят на 100%.

## Master TZ Phases 6–8 — завершены


### Phase 6 — Rattan Intelligence Taxonomy
- Расширен классификатор `_product()`: 12 категорий товара (`RATTAN_SOFA`, `RATTAN_ARMCHAIR`, `RATTAN_GARDEN_SET`, `RATTAN_BAR_STOOL`, `SWING`, `PERGOLA` и т.д.);
- Уточнены B2B пороги: 10+ стульев/предметов переводит роль в `B2B_HORECA`, 9 и менее — `B2C_CONSUMER`;
- Создан калибровочный датасет `fixtures/rattan_calibration.json` (20 золотых примеров RU/UZ);
- Написана группа тестов `tests/test_rattan_intelligence.py` (100% pass).

### Phase 7 — Competitor Demand Gap Analytics
- В `WebQueryService` добавлены `demand_gap_score()` и `demand_gap_overview()`;
- Считается доля неотвеченных коммерческих лидов (`unanswered_rate`), B2B gap (`b2b_gap`) и cross-competitor gap (`multi_source_gap`);
- Панель **Demand Gap** добавлена на страницу конкурента с чётким предупреждением о границе данных (Direct не просматривается);
- Написана группа тестов `tests/test_demand_gap.py` (100% pass).

### Phase 8 — Demand Heatmap (30 Дней)
- Добавлен `demand_heatmap()`: 30-дневная динамика, популярные категории товара и намерения;
- Ограничение безопасности: не более 500 сканируемых строк на запрос;
- Добавлена визуальная панель **Demand Heatmap** в интерфейс карточки конкурента;
- Написана группа тестов `tests/test_demand_heatmap.py` (100% pass);
- 123 теста, Ruff lint и 17 integrity checks проходят на 100%.

## Master TZ Phase 4 — завершён


- `ContactIntelligence` расширена полями профиля DNA: `primary_buyer_role`, `buyer_roles_json`, `evidence_count`, `similarity_vector_json`;
- `primary_buyer_role` агрегируется из всей коммерческой истории лида с приоритетом `B2B_HORECA` > `DESIGNER_CONTRACTOR` > `B2C_CONSUMER`;
- `evidence_count` отображает количество связанных `Evidence`-записей через `PublicSignal` без дополнительных API-вызовов;
- `similarity_vector_json` хранит детерминированный вектор для offline-сравнения аудиторий (товарные интересы, намерения, роль, вертикаль, количество);
- добавлены 4 новых buyer-role сегмента: `designers`, `horeca-b2b`, `high-intent-b2c`, `comparison-shoppers`;
- `_evaluate()` поддерживает критерий `buyer_role` с понятными строками обоснования в `evidence_json`;
- `calculate_contact_similarity()` — детерминированный Jaccard-взвешенный скоринг сходства 0.0–1.0, без внешних вызовов;
- `get_similar_contacts()` — ранжированный список похожих контактов из локальной БД;
- `build_audience_export()` — строгий контроль `ExportEligibility.FIRST_PARTY_ELIGIBLE`: без подтверждённой квалификации контакт в экспорт не попадает;
- приватные атрибуты (phone, email, адреса) не хранятся и не инферируются в similarity vector;
- миграция `a1b2c3d4e5f6` протестирована на текущей и свежей БД;
- 110 тестов, Ruff lint и 17 integrity checks проходят на 100% без внешних API-вызовов.

## Master TZ Phase 3 — завершён

- версия интеллекта зафиксирована как `intelligence_version: "2.0"`;
- скоринг разложен на явные факторы: `intent_strength`, `specificity_score`, `role_score`, `history_boost`, `objection_penalty`;
- добавлена типизация ролей покупателей `BuyerRole`: `B2C_CONSUMER`, `B2B_HORECA`, `DESIGNER_CONTRACTOR`, `JOB_SEEKER`, `UNKNOWN`;
- `LeadAnalysisContext` и `LeadAnalysis` связывают найденные `evidence_ids` напрямую с universal signals и evidence-моделью;
- история скоринга в `contact_events` фиксирует полную декомпозицию факторов, роль покупателя и версию аналитики;
- откалиброван золотой датасет `fixtures/golden_lead_calibration.json` (30+ примеров на RU, UZ Latin, UZ Cyrillic);
- система надежно разделяет стадии воронки, B2B/HoReCa объёмы (10+ шт / ресторан / опт), запросы дизайнеров (3D-модели / проекты), возражения по цене и некоммерческие реакции/вакансии;
- 93 теста, Ruff lint и 17 integrity checks проходят на 100% без внешних API-вызовов.

## Master TZ Phase 2 — завершён

- Telegram outbox получил durable lease с уникальным worker/token и атомарным claim;
- стабильные `idempotency_key` защищены unique-индексами для лидов и значимых изменений;
- зависший claim до начала отправки безопасно возвращается в очередь;
- после начала отправки неизвестный результат переводится в `UNCERTAIN` без автоповтора;
- неоднозначную доставку можно явно подтвердить или безопасно вернуть в очередь с audit fields;
- `chat_id`/`message_id` сохраняются, а обогащение сообщения имеет один edit claim и не более
  одного fallback;
- Dashboard отдельно показывает неопределённые доставки, System объясняет recovery policy;
- integrity scan проверяет оба типа notification targets и idempotency keys;
- миграция `7d2c4e8f1a90` проверена на копии текущей и чистой БД, повторном upgrade,
  downgrade/re-upgrade и schema check;
- подробный контракт: `docs/V4_NOTIFICATION_PIPELINE.md`.

## Master TZ Phase 1 — завершён

- добавлены `Vertical`, `BusinessEntity`, `BusinessAlias`, universal `PublicSignal` и `Evidence`;
- legacy Instagram comments dual-write в universal signal/evidence без изменения старых IDs;
- миграция backfill создаёт по одной business/alias на конкурента и evidence на сигнал;
- unique external identity и `dedupe_key` защищают universal signals от дублей;
- исправлена склейка разных людей при повторном использовании Instagram username;
- добавлен evidence-based Entity Resolution: weak name не auto-merge, strong verified alias — merge;
- fixture Armo/Exon/ротанг даёт одну BusinessEntity без hardcode;
- BOTANIST/Emil сохранён как `NEEDS_VERIFICATION` без выдуманных идентификаторов;
- создан `docs/V4_ARCHITECTURE.md`;
- Phase 2 затем выполнена отдельным проверяемым этапом без изменения Phase 1 IDs.

## Master TZ Phase 0 — завершён

- полностью изучены `LEAD_RADAR_V4_MASTER_TZ_CODEX.md` и
  `CODEX_START_PROMPT_LEAD_RADAR_V4.txt`;
- создан `docs/V4_AUDIT_REPORT.md`: архитектура, Critical/High/Medium риски,
  migration/UI/testing plans и порядок Phases 1–12;
- подтверждённых аварийных P0-багов в текущем локальном режиме нет;
- обнаружены High-риски identity merge, universal signal foundation, N+1 analytics,
  distributed idempotency и public web deployment guard;
- после подтверждения владельца Phase 1 выполнена отдельным проверяемым этапом.

## На какой стадии мы сейчас

**Master Phase 3 из 12 завершена; Phase 4 готова к реализации.**

Ранее выполненные стадии 1–3 старого roadmap сохраняются как рабочий фундамент: CRM,
Mini App, сделки, replay, локальный AI, защита расходов, мультиконкурентный радар и аудитории.
Новый порядок реализации и критерии приёмки зафиксированы в `docs/V4_AUDIT_REPORT.md`.

## Новое в V4.1 Foundation

### System & UI Audit Pass

- исправлена ссылка KPI «Нужно связаться»: теперь она открывает задачи, а не текущий обзор;
- мобильная нижняя навигация переведена в один горизонтально прокручиваемый ряд: все 11 разделов
  доступны и больше не обрезаются;
- определён отсутствовавший design token `--primary`, KPI выровнены в симметричную сетку 4 + 3,
  длинный список кандидатов свёрнут в доступный disclosure-блок;
- фильтры, textarea и настройки конкурентов получили доступные названия; повторный DOM-аудит
  14 основных экранов не нашёл неподписанных полей, duplicate id или horizontal overflow;
- штатный `Ctrl+C` теперь считается чистой остановкой и не печатает traceback `KeyboardInterrupt`;
- browser console чиста, 83 теста и integrity scan проходят без Instagram/OpenAI-вызовов.

### Competitor Intelligence V2

- экран конкурентов считает не vanity-метрики, а наблюдаемый коммерческий спрос: долю сильных
  сигналов, уникальных покупателей, HOT-rate и вопросы о цене, наличии, доставке и количестве;
- отдельная карточка компании показывает эффективность публикаций на 100 наблюдаемых комментариев,
  структуру intent/товаров, реальные вопросы и детерминированные рекомендации менеджеру;
- overlap network считает один контакт один раз для каждой пары конкурентов и не раздувается от
  повторных комментариев у одной компании;
- система прямо отделяет наблюдаемые публичные комментарии от неизвестного: она не видит Direct и
  при текущей конфигурации provider не утверждает, отвечал ли конкурент публично;
- все расчёты выполняются из уже сохранённой БД и не вызывают Instagram/OpenAI.

### Significant Change Detector

- после пересчёта Audience Engine новый сигнал сравнивается с предыдущим сохранённым профилем;
- отдельное изменение создаётся только при новом конкуренте, сильном intent, новой категории,
  количестве 20+/50+, B2B, входе в HOT/high-value, реактивации, росте приоритета или стадии;
- мелкие изменения score игнорируются, а несколько причин одного сигнала объединяются в одно
  понятное событие «Лид стал горячее»;
- `significant_changes` уникален по `lead_id`, immutable `ContactEvent` создаётся в той же
  транзакции, а Telegram outbox уникален по изменению и адресату;
- уведомление отправляется только после DB commit; retry, конкурентные вызовы и повторный ingestion
  не создают дубль;
- первый сигнал не порождает лишнее material-change уведомление, baseline/replay не отправляют его
  в production;
- Command Center показывает изменения за 24 часа, а карточка клиента объясняет переход
  приоритета «было → стало»;
- исправлена реактивация: учитывается последний перерыв 30+ дней, а сегмент истекает через 30 дней.

### Audience Engine

- для каждого контакта строится наблюдаемый коммерческий профиль: стадия, активность, ценность,
  товары, намерения, число сигналов, источников и конкурентов;
- 20 динамических сегментов охватывают HOT-окна, товарный интерес, цену, наличие, доставку,
  количество, B2B / HoReCa, повторный спрос и интерес у нескольких конкурентов;
- membership пересчитываются идемпотентно после анализа и при старте, устаревшее членство
  выключается без удаления истории;
- отдельный экран аудитории показывает состав, реальные агрегаты и детерминированный campaign
  brief без дополнительных AI-вызовов;
- карточка клиента показывает только интересы из наблюдаемых публичных источников и прямо
  предупреждает, что это не полный портрет человека;
- username никогда не считается согласием на экспорт: экспорт возможен только после сохранения
  менеджером first-party телефона и факта квалификации;
- на текущей БД: 25 профилей, 20 сегментов, 500 уникальных membership и 0 дублей.

### Signal First и надёжная доставка

- каждый новый уникальный публичный комментарий теперь атомарно создаёт `Comment`,
  `PublicSignal` и `ContactEvent`; транзакция завершается до Telegram-действий;
- рабочая оболочка лида получает статус `ANALYZING` и фиксируется до анализа;
- при политике по умолчанию менеджер сразу получает первый сигнал, а анализ запускается после него;
- итоговый разбор обновляет исходное Telegram-сообщение; невозможность edit даёт ровно один
  короткий follow-up;
- `notification_logs` хранит `chat_id`, `message_id`, версию содержимого и состояние fallback;
- retry и повторный ingestion не создают второе уведомление; baseline и replay production-сообщения
  не отправляют;
- доступны режимы `ALL_NEW_COMMENTS`, `COMMERCIAL_ONLY`, `HOT_ONLY` глобально и отдельно для
  каждого конкурента; в UI они объяснены простыми русскими словами;
- сбой AI переводит лид в «Нужна дополнительная проверка», но не скрывает его и не уничтожает
  сохранённый сигнал.

### Quality pass V4.1

- цепочка миграций до `c93a1f7d2e40` проверена на рабочей и пустой SQLite-базе;
- integrity scan теперь отдельно проверяет дубли `PublicSignal`;
- исправлены вводящие в заблуждение статусы Telegram в replay и технические AI-метки в UI;
- `ANALYZING` и `AI_PENDING` считаются рабочими состояниями: менеджер может взять такой лид;
- Audience Engine, Significant Change Detector и Competitor Intelligence V2 завершены и проверены
  без внешних вызовов.

## Сохраняется из V3.5

### Глубокий AI-анализ

- структурированный результат расширен: confidence, стадия покупки, срочность, горизонт решения,
  доказательства, риски и рекомендуемое действие менеджеру;
- OpenAI получает стабильную инструкцию отдельно от динамического контекста, Structured Outputs,
  `store=false`, cache key V2 и reasoning effort `medium`;
- добавлены защита от ложного совпадения при отрицании, одновременный разбор нескольких намерений,
  ценовые возражения и срочность RU / UZ Latin / UZ Cyrillic;
- расширенный разбор сохраняется в `leads.analysis_details`, входит в новые immutable events и
  остаётся обратносуместимым со старым кешем;
- все 28 сохранённых лидов обогащены локально; повторный backfill обновил `0` строк.

### Интерфейс V3.5

- карточка лида показывает manager-ready AI-разбор вместо одной строки причины;
- Radar на узком экране превращается в карточки и больше не сжимает шесть колонок;
- формы Radar перестраиваются без обрезанных кнопок;
- светлая liquid-glass палитра распространена на hero лида, воронку и action controls.

Live Instagram и OpenAI не включались; текущие лимиты и пауза поиска сохранены.

## Сохраняется из V3.4

### Светлый интерфейс и доступность

- весь Mini App переведён на светлую liquid-glass систему без изменения CRM-логики;
- панели, таблицы, формы, модальные окна и статусы получили единые светлые токены и контраст;
- добавлены адаптивные Lucide-иконки с текстовым fallback при недоступности CDN;
- добавлены skip-link, `aria-current`, семантическая метка навигации и видимый keyboard focus;
- предусмотрены fallback без `backdrop-filter` и отключение анимаций через `prefers-reduced-motion`;
- browser MCP подключён к локальному приложению для визуальной проверки Dashboard и Radar.

Поиск лидов, live Instagram и OpenAI не включались; визуальная доработка не расходует внешние
API-токены.

## Сохраняется из V3.3

### Качество лидов

- 28 сохранённых сигналов разобраны локально без OpenAI: 8 HOT, 17 не-лидов, 3 AI_PENDING;
- локальные правила дополнены рассрочкой, прямым заказом, оптом и HoReCa-сценариями;
- добавлены отрицательные признаки вакансий и нерелевантных фраз;
- история и причины решения остаются видимыми в карточке лида.

### Доставка менеджеру

- Telegram работает в полном polling-режиме даже при остановленном Instagram-поиске;
- повторная доставка outbox больше не зависит от цикла мониторинга;
- назначенный лид отправляется своему менеджеру, неназначенный HOT-лид — администраторам;
- уникальный ключ `lead_id + chat_id` не допускает повторной отправки одной карточки адресату.

### Карта рынка и интерфейс

- в радаре 16 подтверждённых компаний, активна только AIKO;
- добавлены Mudo Concept, Divan.uz, Homedit, Komfort Elit и ERGO — все на паузе;
- три соответствующих market candidates помечены как перенесённые, а не продублированы;
- на Dashboard показаны очередь разбора и состояние доставки менеджерам;
- на Radar появилась сводка: все сигналы / не разобраны / лиды / HOT / отсеяно;
- кнопка поиска явно заблокирована, когда `LEAD_SEARCH_ENABLED=false`.

## Сохраняется из V3.2

### Market intelligence

- встроенный каталог подтверждённых конкурентов;
- idempotent market catalog и отдельный список market candidates;
- новые компании создаются на паузе и не повышают расход API;
- отдельная уверенность кандидата и причина, почему он интересен;
- продвижение кандидата в реальный мониторинг через Mini App;
- сайт и Instagram компании видны в карте рынка;
- idempotent catalog sync на старте приложения;
- ручные настройки active/tier пользователя не перезаписываются повторной синхронизацией.

### Более сильный lead intelligence

- HOT-rate по каждому конкуренту;
- системная рекомендация: усилить мониторинг / оставить / фоновый / набираем данные;
- один Contact теперь явно показывает число разных источников;
- если пользователь найден у нескольких конкурентов, Mini App отмечает это как сильный сигнал;
- локальный lead score получает ограниченный дополнительный boost за cross-competitor history.

### Продуктовая понятность

- новый раздел `Развитие`;
- на Dashboard видна текущая стадия проекта;
- дорожная карта из 7 стадий встроена в Mini App;
- раздел `Конкуренты` разделён на рабочий мониторинг и разведку рынка.

## Сохраняется из V3.1

- Contacts / Signals / Leads / Deals / ContactEvents;
- Radar, Kanban, client 360, Tasks, Deals, Analytics;
- Telegram HOT alerts;
- локальный RU / UZ Latin / UZ Cyrillic classifier;
- AI_PENDING;
- AI cache;
- replay/mock;
- truthful comment coverage;
- cursor pagination + stop-on-known;
- daily/per-scan budgets;
- double live unlock;
- server-side live confirmation;
- Telegram Mini App auth preparation.

## Проверки текущей локальной сборки

- Python compileall: passed.
- `ruff check app scripts`: passed.
- Alembic schema check: passed, новых операций не требуется.
- Проверка целостности: passed; дубли по comment ID, post URL, lead/comment, deal/lead и
  notification target отсутствуют.
- Исходные данные сохранены: 25 контактов, 12 постов и 28 комментариев. После локальной
  квалификации история расширилась до 53 неизменяемых событий и 28 результатов разбора.
- Результат синхронизации: **16 competitors / 1 active / 24 открытых market candidates**.
- Повторная синхронизация каталога дважды создала `0` конкурентов и `0` кандидатов.
- Локальный web smoke: `/health` и `/` успешны; `/api/scan` возвращает блокировку `409`.
- полный `pytest`: **83 passed**; тесты не обращаются к Instagram/OpenAI и не расходуют API-токены.
- `ruff check .`, compileall и data-integrity check: passed.
- новые `/competitors` и `/competitors/{id}` проверены на рабочей БД: browser console чиста,
  horizontal overflow отсутствует.
- Alembic head: `c93a1f7d2e40`; этот этап не меняет схему БД.
- Внешние Instagram/OpenAI вызовы при переносе и проверке: **0**.
- Ручной smoke без pytest подтвердил маршрутизацию назначенному менеджеру и отсутствие повторной
  отправки: первая доставка `1`, повторная `0`.

Поиск лидов полностью приостановлен через `LEAD_SEARCH_ENABLED=false`: ручные команды,
веб-кнопка, `--once` и расписание не могут запустить цикл. Дополнительно live-флаги выключены,
лимиты равны нулю, AI работает в режиме `rules`, внешний unlock пуст.

## Следующая цель

Следующий вертикальный этап V4.1 — **Demand Gap Engine**: сопоставление наблюдаемого спроса с
управляемым каталогом предложений и объяснимые пробелы без домыслов о скрытых действиях
конкурентов. Для начала потребуется импорт собственного каталога товаров/категорий.

Live-поиск остаётся выключенным до отдельного решения владельца; разработка продолжается на
накопленной БД и replay без внешнего расхода.

Полная дорожная карта: `ROADMAP.md`.
