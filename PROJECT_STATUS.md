# Lead Radar — состояние проекта

## Текущая версия

**PERSISTENT AI CHAT · FUNNEL UX · QA 55 · LIVE PILOT READY**

Контрольная точка 2026-09-01 (QA5): ROI smoke 89x + gross margin 90% на /economics,
browser visual 720px OK (economics/leads), PR #1 merged в main. **387 passed, 1 skipped**.

Контрольная точка 2026-09-01 (QA4): полная русификация economics (токены, HOT/WON,
валовая прибыль), smoke WON+revenue 12.5M UZS, pilot preflight test, mobile CSS
audit расширен. **385 passed, 1 skipped**.

Контрольная точка 2026-09-01 (QA3): economics split test (30 confirmed + 10
estimated = 75%), smoke competitor/audience detail по реальным ID, русификация
audience_quality таблиц, mobile responsive-table audit. **383 passed, 1 skipped**.

Контрольная точка 2026-09-01 (QA2): русификация admin-страниц (discovery,
analytics, catalog, audiences, openings, competitor/audience detail), motion на всех
hero-секциях, +15 smoke-тестов. Offline gate: **377 passed, 1 skipped**.

Контрольная точка 2026-09-01 (вечер): QA-план 55 действий закрыт — economics
русифицирован (confirmed/estimated credits), smoke-тесты всех страниц и funnel API chain,
motion на economics/competitors/system. Offline gate: **362 passed, 1 skipped**. Live
readiness: **READY FOR LIVE PILOT**, UNCERTAIN=0.

Контрольная точка 2026-09-01 (день): persistent `/agent` (сессии в БД, approval-gated
write tools), исправлен критический баг `app.js` (дублирующий `escapeHtml` ломал воронку
лидов), UI polish v13.11 (motion, funnel track, typing indicator). 4 UNCERTAIN OpenAI
reservations reconciled (`spent=false`). CI GREEN run `33499039391` (sqlite + postgres).

Контрольная точка 2026-09-01: фоновая очередь `LeadAnalysisPipeline` (concurrency 1–10 в
`operational_controls`, Alembic `a2b3c4d5e6f7`) — Instagram-scan не блокируется OpenAI.
Radar UI: лента significant changes + HOT, live-баннер, toast/звук, polling `/api/radar/feed`.
Retry AI и batch analyze — async через pipeline. Offline gate: **333 passed, 1 skipped**.

Controlled pilot: `scripts/arm_controlled_pilot.py` (aiko.uz only, 5 credits, Radar+OpenAI ON),
preflight `scripts/prepare_controlled_pilot.py` (без live). Meta live OFF.

Контрольная точка 2026-08-31 (ночь): ротанг — отдельный портфель источников.
`Competitor.vertical` = enrollment (FURNITURE / ARTIFICIAL_RATTAN); таксономия
размечает signal/lead, но не auto-enroll. Stub `rattan_classifier_service` и
калибровочные classifier-тесты удалены. Alembic `f1a8c3e74b90` сбрасывает
ошибочный auto-promote портфеля. `/rattan` пуст, пока оператор не выберет
вертикаль «Ротанг» у конкурента. Offline gate: **318 passed, 1 skipped**.

Ранее вечером 2026-08-31: master unlock в `.env` + тумблеры
`radar_live_armed` / `openai_live_armed` в БД (`operational_controls`, Alembic
`e4f7a1c93b20`). UI: Radar/System «Включить Live Radar» / «OpenAI». Spend только
когда тумблер armed. Полный `python -m app.main` (web+bot+notifications).
Meta live OFF. Расписание выкл (`INSTAGRAM_MANUAL_LIVE_SCAN_ONLY`).

Текущая программа: offline hardening закрыт по P0 CI/spend; следующий milestone —
controlled Radar pilot (5–10 ScrapeCreators credits). Старые заявления «100% complete»
и «Production Ready» не являются доказательством готовности.

Контрольная точка ранее 2026-08-31: **314+ тестов**, Ruff clean, **CI matrix GREEN 2/2**
(sqlite + postgres, commit `9bf6dff`, Alembic head `d9e4b1c82a70`).
Postgres concurrency gate: `tests/test_postgres_budget_concurrency.py` (CI postgres only).
Preflight: `python -m scripts.prepare_controlled_pilot` (без live calls).

## Hardening sprint (после review HEAD 9a9e2ca)

P0/P1 закрыты в коде:
- initial schema: уникальные имена `uq_contacts_platform_username` / `uq_contacts_platform_user_id`;
  normalize migration idempotent;
- provider budget seed через SQLAlchemy `active=True` (dialect-safe);
- `ScanBudget.default_limit` + `current_cycle_limit`; manual Deep scan не протекает в scheduler;
- external fail после `call_started` без provider credit → `UNCERTAIN`, не invented charge;
- PostgreSQL `pg_advisory_xact_lock` в `reserve_budget` + concurrent monthly cap test;
- `/economics`: confirmed vs estimated credits + coverage %;
- Postgres `backup_present` больше не auto-True (нужен `.runtime/postgres_backup_verified`);
- Alembic: короткие CHECK-токены под PG 63 chars; `d9e4b1c82a70` normalize на Postgres;
  `alembic/env.py` не падает на исторический CHECK name drift.

**Phase 9 не завершена.** Meta live OFF. Live pilot — только по явному разрешению.

## Master Phase 9 — Deployment readiness (offline, в процессе)

- `GET /ready` — readiness probe: DB ping + Alembic head + drift check (`503` при блокерах);
- `GET /health` — liveness без DB check (как раньше);
- `PORT` env переопределяет `WEB_PORT` (Railway);
- `LOG_FORMAT=json` — structured logs в production;
- `DeploymentReadinessService` — общая логика для `/ready` и `live_readiness_check.py`;
- `railway.json`: `--web-only`, `healthcheckPath=/ready`;
- `Dockerfile`: `HEALTHCHECK`, default `--web-only`;
- `docs/DEPLOYMENT.md` — runbook env/probes/rollback;
- `meta.create_campaign_draft` — `MetaAdsService` Graph API (campaign + adset PAUSED) при live unlock;
- PostgreSQL CI matrix в GitHub Actions (sqlite + postgres);
- SIGTERM/SIGINT graceful shutdown для full-stack и web-only;
- bug-hunt pass 3: monitor errors logged; MCP catch-all INTERNAL; export `ineligible_count`;
- полный offline gate: **310 tests passed**; внешних вызовов: **0**.
- backlog: Meta Custom Audience confirmed export; SIGTERM на Windows dev.

## Master Phase 8 — UI final hardening (завершён offline)

- `/system`: grounded agent workspace (`data-agent-query` → `/api/agent/query`) и export recipes dry-run UI;
- `/audiences/{slug}`: segment-bound export dry-run preview;
- `/leads/{id}`, `/contacts/{id}`: agent panels с preset queries;
- `/economics`: responsive tables (sources/providers/verticals);
- `/dashboard`: LOST funnel badge;
- mobile: Telegram BackButton + safe-area;
- **auth fail-closed**: mutating `POST /api/*` возвращает 403 без `WEB_MANAGER_ID` в dev;
  `/api/docs` и `/openapi.json` скрыты когда `web_auth_enabled=false`;
- `MCPWriteToolService`: `crm.assign_lead` через `LeadWorkflowService.assign_manager` (approval-gated);
- bug-hunt pass 2: export dry-run audit `manager_id`, pricing dead code, audience.dna namespace;
- CSS/JS cache `13.2.0-phase8-ui`;
- полный offline gate: **303 tests passed**; внешних вызовов: **0**.

## Pilot Cockpit UI + spend hardening (offline)

- навигация упрощена: 5 primary + 5 в «Ещё»; topbar «Проверить сейчас» с любой страницы;
- `/` dashboard: «Кабина пилота», quick-actions (Radar, HOT, задачи, экономика, конкуренты, диагностика);
- модалка `#scan-quick`: выбор 5 / 10 / 20 / custom credits перед запуском Radar;
- `ProviderCallUncertainError`: fallback не активируется после `call_started` без credit proof (P0 double-spend fix);
- OpenAI после `call_started` → `mark_reservation_uncertain`, не `finalize(units=1)` (P1);
- CSS/JS cache `13.3.0-pilot-cockpit`;
- полный offline gate: **316 passed, 1 skipped**; ruff clean; внешних вызовов: **0**.

## Bug-hunt pass 13.8.2 (offline)

- AI claim-lost после delivered OpenAI: finalize ledger + park SUCCEEDED, без второго paid call;
- openings без `contact_id`: идемпотентный lookup по place_name/city/PENDING_REVIEW;
- удалён мёртвый unsafe `ExternalUsageService.record()` (без reservation/idempotency).

## Bug-hunt pass 13.8.1 (offline)

После 15+7 проходов по UI/AI/bot/spend:

- `/analytics?days=` реально режет `Lead.created_at` / deals / feedback; ссылка Dashboard → `/`;
- leftover ScrapeCreators credits после parse-fail больше не приписываются следующему вызову;
- AI routing: sticky `lead_id` не перехватывает audience/openings/lead-search; «открытые лиды» ≠ `google.openings`;
- retry AI_PENDING поднимает stale `ANALYZING` (>15 мин);
- CSS: `--space-8`, валидный `rgba()`, mobile shell `padding: 0`, `.tag.warn`;
- nav: Каталог и Поиск в furniture «Ещё»; bot `/pending` в commands и reply-keyboard;
- cache `13.8.1-bug-hunt`.

## Airy UI V3.5 + page polish (offline)

- единый spacing rhythm, Inter, heroes contacts/tasks/deals/openings/analytics;
- `/openings` и `/system` responsive tables; analytics period chips;
- CSS/JS cache `13.8.0-ui-polish` (commit `658cd37`).

## System pass UI + AI routing (offline)

- `catalog.recommend` read tool: «Что предложить» с `lead_id` больше не уходит в `lead.explain_score`;
- intent-first routing в `AgentSessionService`; человекочитаемый синтез explain/catalog;
- `/api/leads/retry-pending` + кнопки на dashboard/radar/system;
- `/system`: hero cockpit, TOC anchors, operator actions;
- `rattan-metrics` 4-col grid; leads kanban score mask; filter `q` сохраняется;
- dashboard funnel пропорционален peak; local analyze alert;
- bot: `/pending`, deep link «🌐 Карточка» в Telegram cards, dynamic `/help`;
- CSS/JS cache `13.6.0-system-pass`;
- полный offline gate: **321 passed, 1 skipped**; ruff clean; внешних вызовов: **0**.

## Layout fix radar metrics (offline)

- `radar-metrics` отдельно от `dashboard-metrics`; hero-status на radar/leads/economics;
- cache `13.5.1-layout-fix` (commit `863405f`).

## Economics + Radar/Leads UI pass (offline)

- `/economics`: hero KPI, `safe_attr` для credit accuracy, segmented period control; fix 500 от stale server;
- global AI modal `#agent-quick` + кнопка AI в topbar; rich `renderAgentAnswer`;
- `/radar`: hero + metrics summary; `/leads`: hero, quick filters, kanban polish;
- lead/contact detail: AI presets + rich result panels (`#lead-agent-result`, `#contact-agent-result`);
- Telegram bot: `build_main_menu()` с WebApp «🌐 Кабина» при HTTPS `WEB_PUBLIC_URL`;
- CSS/JS cache `13.5.0-radar-leads-agent`;
- полный offline gate: **319 passed, 1 skipped**; ruff clean; внешних вызовов: **0**.

## Master Phase 7 — Grounded Agent завершён

- `MCPReadToolService` подключает read tools к SQLite:
  `lead.search`, `lead.explain_score`, `audience.dna`, `competitor.opportunities`,
  `rattan.company_analysis`, `google.openings`;
- `AllowedAudienceRegistry` и `AudienceMembershipResolver` ограничивают audience facts
  ACTIVE registry slugs и persisted evidence;
- `AgentSessionService` выполняет deterministic offline synthesis без fake catalog/SKU/discount;
- `/api/agent/query` возвращает grounded payload с `evidence_ids` и tool trace;
- write tools: `crm.assign_lead` wired через approval gate; `meta.*` остаются NOT_CONNECTED;
- migration не потребовалась; полный offline gate: **284 tests passed**; внешних вызовов: **0**.

## Master Phase 6 — Independent quality gates завершён

- `IndependentQualityGatesService` оценивает отдельные unseen-наборы:
  lead (`fixtures/lead_intelligence_unseen_v1.json`, 56 cases),
  rattan (`fixtures/rattan_unseen_v1.json`, 35 cases),
  audience (`audience_membership_unseen_cases.py`, 106 labeled decisions);
- метрики precision/recall/F1/accuracy и intent/layer confusion считаются детерминированно;
- calibration (`lead_intelligence_v3_eval`), challenge (`lead_intelligence_challenge_v1`) и
  robustness roots (`golden_lead_calibration`, `rattan_vertical_v2_golden`) не смешиваются с unseen;
- `/system` показывает три gate cards с PASS/FAIL и mismatch details;
- migration не потребовалась; полный offline gate: **275 tests passed**; внешних вызовов: **0**.

## Master Phase 5 — Audience correctness завершён

- `calculate_membership_confidence()` заменяет простое среднее evidence confidence;
  одно слабое evidence не даёт завышенный score;
- `rattan_role` в `AudienceEngine._evaluate()` с `RATTAN_ROLE_CRITERIA_MAP`
  (RAW_SELLER, MANUFACTURER, READY_FURNITURE_SELLER, IMPORT_DISTRIBUTION);
- `AudienceQualityService` считает `AudienceHealthSnapshot` (HEALTHY/LOW_DATA/STALE/NOISY/NEEDS_REVIEW/NOT_EXPORTABLE)
  и Jaccard overlap по активным membership;
- `/audiences/quality` — health table + overlap analytics; `/audiences` показывает health badge;
- comparison decay (45d source window) уже был в Phase 1 — без изменений;
- migration не потребовалась; полный offline gate: **272 tests passed**; внешних вызовов: **0**.

## Master Phase 4 — Economics завершён

- отдельная страница `/economics` с nav «Экономика»; `/analytics` оставлен только для market intelligence;
- `EconomicsPageService` собирает wallet/burn/months из `ProviderCreditBudgetService`, USD funnel из
  `UnitEconomicsEngine` и credits-per-outcome из `CostEvent.units` для ScrapeCreators;
- operation breakdown сравнивает Comments/Discovery/Profiles/Fallback с planning targets policy;
- HOT/B2B/WON и revenue/GP per 1 000 credits считаются fail-closed (`None` без фактов);
- OpenAI `response.usage` извлекается в `OpenAILeadAnalyzer` и пишется в `CostEvent`/`AIRequest`
  через `finalize_reservation(input_tokens, output_tokens)`;
- Bright Data / Infrastructure показываются только при наличии cost events;
- migration не потребовалась; полный offline gate: **267 tests passed**; внешних вызовов: **0**.

## Master Phase 3 — Adaptive Monitoring завершён

- deterministic policy назначает `ACTIVE / WARM / COLD / DORMANT` только из наблюдаемых
  фактов и хранит state, priority, reasons, policy version и `next_scan_at` у конкурента;
- due scheduler исключает ещё не наступившие проверки и ранжирует остальные по состоянию,
  Tier, полезной активности, HOT/B2B, просрочке и ошибкам без GPT и fixed polling;
- Radar сначала завершает discovery coverage по ранжированным источникам, затем глобально
  ранжирует найденные Reel и расходует остаток общего scan budget на comment refresh;
- zero comments, unchanged posts и известный comment продолжают экономить paid requests;
  dormant означает редкий discovery, а не окончательное исключение источника;
- `MonitorRun.stats_json` хранит skipped unchanged/zero comments/pagination stop/not due,
  budget deferred и avoided request facts; Radar показывает их в результате проверки;
- migration `c8f3a1d57b20` проверена fresh, repeated, downgrade/re-upgrade и на рабочей БД
  после backup; schema drift отсутствует;
- desktop 1440px/mobile 390px проверены read-only на `/radar`, `/system`, `/competitors`;
  overflow и JS errors не обнаружены;
- полный offline gate: **256 tests passed**, Ruff, compileall, JS syntax, Alembic и integrity
  чистые; внешних вызовов, ScrapeCreators credits и OpenAI tokens: **0**.

## Master Phase 2 — Radar Credit Budget завершён

- `ProviderBudgetPolicy` хранит ScrapeCreators target `3000`, soft `3500`, hard `3800`,
  default scan `10`, manual max `50` и плановые категории расхода;
- `ProviderCreditSnapshot` хранит только явно маркированные `API_RESPONSE`,
  `BALANCE_ENDPOINT`, `MANUAL` или `LOCAL_ESTIMATE`; текущий баланс остаётся `UNKNOWN`,
  пока реальный факт не получен;
- месячный hard limit проверяется в той же SQLite write transaction, что и durable reservation;
  дневной, месячный, ручной предел и подтверждённый остаток одновременно ограничивают scan;
- ScrapeCreators adapter извлекает только явные `credits_remaining`/`credits_charged`;
  provider-confirmed charge заменяет estimate, превышение резерва сохраняется и останавливает run;
- `MonitorRun` хранит requested/effective/actual credits, balance/month before/after,
  operation breakdown и нормальную причину budget stop;
- `/api/scan/preview` не делает внешних вызовов и возвращает wallet, burn, forecast,
  месячные пределы, эффективный cap и blocking reasons;
- `/radar` получил budget-first карточку, пресеты `5/10/20/40/custom`, live confirmation
  и factual result card; desktop 1440px/mobile 390px проверены без overflow;
- migration `b7d9e2a46f10` проверена fresh, downgrade/re-upgrade и на рабочей БД после backup;
- полный offline gate: **253 tests passed**, Ruff, compileall, JS syntax, Alembic и integrity чистые;
  внешних вызовов, ScrapeCreators credits и OpenAI tokens: **0**.

## Master Phase 1 — Remaining P0 correctness завершён

- `live_readiness_check.py` разделяет `READY FOR OFFLINE USE` и `LIVE BLOCKED`; unlock,
  provider credentials, Telegram admin, backup, DB health, Alembic drift и `UNCERTAIN`
  являются блокирующими условиями, а не warnings;
- AI history больше не содержит произвольные raw-комментарии: `ValidatedPreviousSignal`
  строится только из commercial Lead + реальных Evidence + InterestEvidence той же vertical;
- `previous_interests` выводятся из активных `ContactInterestProfile` или валидированной
  коммерческой истории, но не из произвольного `Lead.product_category`;
- Audience source diversity требует индивидуальный decayed score и confidence каждого
  InterestEvidence; comparison window ограничен 45 днями;
- начатая операция с неизвестным исходом переводится в `UNCERTAIN`, не создаёт ложный
  usage/cost fact и продолжает удерживать бюджет до reconciliation;
- runtime остановлен; Instagram, Telegram, OpenAI, Meta и другие внешние вызовы не выполнялись;
- полный offline gate: **245 tests passed**, Ruff, compileall, integrity и Alembic check чистые.

## Premium Glass UI — большой проход завершён

- light-glass токены сведены в единую палитру; устранены активные тёмные остатки темы;
- desktop shell получил согласованные Lucide-иконки и более ясные active/hover состояния;
- мобильная навигация ограничена четырьмя основными разделами и доступной панелью «Ещё»;
- switcher вертикалей оформлен как семантическая сегментированная навигация;
- добавлены entrance/stagger, feedback, progress, modal и loading-анимации с полным
  `prefers-reduced-motion`;
- формы сохраняют позицию прокрутки после подтверждённой перезагрузки, modal удерживает focus;
- таблица клиентов превращается в читаемые mobile cards, фильтры закреплены на длинных страницах;
- cache versions синхронизированы для основного shell и auth;
- UI contract расширен; полный gate: **240 tests passed**, Ruff, compileall и JS syntax check чистые.

## Stage 5 — Unit Economics завершён

- rolling revenue из `Deal.final_amount` заменена acquisition-cohort расчётом из immutable
  `DealSaleSnapshot`;
- versioned `FxRatePolicy` хранит только manager-confirmed исторические курсы без внешнего API;
- gross profit и margin доступны только при полном sale snapshot, COGS и FX;
- ROI учитывает только direct lead-attributed cost events и блокируется при unknown price,
  отсутствующем FX, COGS, snapshot или нулевых расходах;
- dashboard и competitor revenue больше не суммируют редактируемые deal amounts;
- повреждённый pricing config с отсутствующей unit/token price не превращает расход в ложный `$0`;
- UI показывает точную причину неполноты и позволяет admin версионировать FX;
- migration `a3c8f7d24e10` проверена fresh/repeated/downgrade и на рабочей БД после backup;
- полный offline gate: **238 tests passed**, Ruff, compileall, Alembic и integrity чистые.

## Stage 4 — Catalog → Offer → Demand Gap завершён

- свойства category, price, stock и COGS имеют timestamps/manager confirmation и versioned audit;
- CSV импорт работает через dry-run diff и атомарный apply, повтор идемпотентен, а подтверждённые
  факты не перезаписываются;
- Next Best Action ранжирует только активные товары подтверждённой категории, объясняет score,
  учитывает остаток, MOQ и не обещает наличие при неизвестном stock;
- WON связывается с Product и создаёт единственный immutable `DealSaleSnapshot` с ценой, COGS,
  версией каталога, валютой продажи и Evidence IDs;
- карточка конкурента отделяет нашу неразобранную очередь от поведения конкурента и показывает
  измеримое покрытие наблюдаемого спроса подтверждённым каталогом;
- удалён недоказуемый генератор «неотвеченного спроса» и рекламных рекомендаций;
- migration `f2a5b8d13c70` проверена на fresh/repeated/downgrade и рабочей БД после backup;
- полный offline gate: **235 tests passed**, Ruff, compileall, Alembic и integrity чистые.

## Stage 3 — Workflow integrity завершён

- CRM запрещает связывать ответ/задачу с лидом другого контакта;
- одинаковая открытая задача повторно возвращает существующую запись и не дублирует ContactEvent;
- WON/LOST повторы с тем же payload идемпотентны, а конфликтующий повтор не переписывает сделку;
- закрытая сделка больше не редактируется через общий upsert; quantity/amount проверяются в service;
- review сигнала открытия идемпотентен и запрещает заменить уже принятое решение;
- `(contact_id, place_name)` защищён DB unique constraint с race-safe возвратом существующей записи;
- конкурентное продвижение кандидата обрабатывает unique race и возвращает одну компанию;
- повтор той же версии pricing больше не создаёт новую историческую строку;
- migration `e1f4a7c92b60` проверена на рабочей БД после backup, fresh, downgrade/re-upgrade;
- integrity scan теперь покрывает opening signals;
- полный offline gate: **232 tests passed**, Ruff, compileall, Alembic и integrity чистые.

## Stage 2 — Production security boundary завершён

- публичный host/URL без Telegram auth и HTTPS теперь отклоняется до запуска;
- web-доступ разделён на непересекающиеся роли viewer/manager/admin;
- роль и allowlist перепроверяются на каждом запросе, удаление ID отзывает активную сессию;
- все mutating requests требуют подписанную cookie и session-bound CSRF token;
- системные, import, catalog, competitor, pricing и scan операции доступны только admin;
- добавлены trusted host, CSP, no-store, nosniff, referrer/permissions headers и HSTS;
- Telegram `initData` по умолчанию действует 300 секунд вместо суток;
- контракт описан в `docs/WEB_SECURITY_BOUNDARY.md`;
- полный offline gate: **229 tests passed**, Ruff, compileall, Alembic и integrity чистые.

## Stage 1 — Schema contract завершён

- именованные Product/Meta unique constraints отражены в ORM metadata;
- `Product.vertical` согласован с существующим `VARCHAR(32)` контрактом;
- новая миграция не создана, поскольку фактическая схема уже была корректной, а drift находился
  только в metadata; лишний rebuild SQLite создал бы необоснованный риск;
- CI теперь запускает `alembic check` на fresh и existing DB и data-integrity scan;
- полный offline gate: **224 tests passed**, Ruff, compileall, Alembic и integrity чистые.

## Честная матрица готовности

| Feature | Implementation status | Test status | Live tested | Production ready |
|---|---|---|---|---|
| Audit + network freeze | Implemented | Offline automated | No | No |
| AI request/budget ledger | Phase B hardened | 186 offline tests + concurrency + migration | No | No |
| Cost ledger & pricing | OFFLINE · durable ledger/config implemented | 190 offline tests + migration | No | No |
| Lead Scoring V3 | OFFLINE · evidence-first rule pipeline | 200 calibration + 36 challenge scenarios + component tests | No | No |
| Audience Intelligence V4 | OFFLINE · governed registry foundation implemented | 217 offline tests; audience golden expansion pending | UI offline | No |
| Rattan Vertical V2 | OFFLINE · taxonomy safety hardened | 30 golden + 194 repository tests | UI offline | No |
| Unit Economics | OFFLINE · snapshot/COGS/cohort/historical FX, fail-closed margin and ROI | 238 repository tests + fresh/repeated migration + UI render | No | No |
| Discovery Center / Diff Engine | OFFLINE · CSV/XLSX review queue implemented | Repository tests + migration + UI render | No | No |
| Product Catalog / Next Best Action | OFFLINE · versioned confirmation, protected CSV diff/apply, grounded ranking and sale snapshots | 235 repository tests + fresh/repeated migration + UI render | No | No |
| Premium UI / Telegram Bot | Web auth/RBAC/CSRF + UI hardening + durable outbox implemented | 229 offline tests; delivery dry-run only | Delivery not run | No |
| Real Agent / MCP | OFFLINE · read tools DB-backed; write tools NOT_CONNECTED | 284 offline tests; grounded /api/agent/query | No | No |
| Meta / Google | Not connected | Offline prototype only | No | No |
| Offline 500–1000 signal pilot | 600-case robustness replay passed | 60 curated roots × 10 variants; unseen corpus pending | No | No |
| Controlled live pilot | Ready to schedule | CI green; preflight script; awaiting explicit unlock + 5–10 credit cap | No | No |

## Audience Intelligence V4.1 — facets and Meta activation boundary

- добавлен composable `AudienceFacetQuery`: фильтры уточняют membership и не создают
  новые audience definitions;
- в карточке аудитории доступны product/intent/role/recency/confidence/value/city/source/
  manager/outcome facets; backend также поддерживает stage, quantity, horizon и rattan facets;
- добавлены отдельные `MetaAudienceBlueprint`, `MetaTargetingRecipe`, `MetaInterest`,
  `MetaInterestMapping`, `MetaExportCandidate` и `MetaAudienceSync`;
- локальный sync идемпотентно создаёт планы со статусом `NOT_CONNECTED`, пустыми interest
  IDs и без внешних audience IDs;
- удалены вымышленные названия Meta interests, неподтверждённые скидки и ложные campaign
  promises из старого recipe engine;
- недоступный confirmed export теперь честно возвращает `NOT_CONNECTED` и не переводит
  контакт в `EXPORTED`; privacy-safe dry-run остаётся доступным;
- миграция `d6b1e4f92a50` проверена повторно на рабочей и чистой SQLite БД;
- полный offline gate: **223 tests passed**, Ruff и compileall чистые;
- платные/live Meta, Instagram, OpenAI и Telegram вызовы не выполнялись.

## Audience Intelligence V4 — governed registry foundation

- добавлен конечный реестр из 28 канонических `AudienceDefinition`; произвольное
  создание сегментов в runtime не разрешено;
- определения разделены по family/level/status/strategy и содержат минимумы Evidence,
  confidence/current score, recency/decay metadata и честный Meta use case;
- 20 доказуемых сейчас аудиторий имеют статус `ACTIVE`; 8 неподдержанных role/outcome
  определений остаются `DRAFT` и не получают memberships;
- прежние time/quantity/competitor микросегменты выводятся из активного реестра без
  удаления исторических записей;
- город, район, возраст, пол, язык, точная дата/оценка/quantity, менеджер, конкурент,
  Reel/post/SKU/цвет/размер закреплены как facets, а не новые аудитории;
- intent/value/fit и high-intent membership используют текущий decayed intent score
  вместо исторического максимума;
- competitor comparison учитывает только действующие коммерческие Evidence: реакция и
  истёкший второй источник не создают аудиторию;
- membership confidence вычисляется из confidence связанных Evidence и больше не
  копируется из value score;
- новая Alembic-миграция `c5a9f2e81d40` проверена повторным upgrade на рабочей БД и
  полной цепочкой на пустой SQLite БД;
- UI показывает family, level, strategy, Meta use case и минимальный Evidence floor;
- полный offline gate: **217 tests passed**, Ruff/compileall проверяются перед commit;
  Instagram/OpenAI/Telegram/Meta live-вызовы не выполнялись.

## Phase C — Lead Scoring V3

- реальный rule pipeline переведён на Intelligence `3.0` с отдельными component scores;
- добавлены `CommercialSignalQuality`, explainable priority и отдельный confidence;
- реакции и шум исключены из history/multi-competitor boost;
- sequence progression сильнее одинаковых повторов, повторения имеют diminishing returns;
- intent-specific decay реально используется в history и Audience activity;
- `B2BPolicy 1.0` централизует contextual/30+/50+ thresholds;
- AI fingerprint учитывает только коммерческую историю, stable contact identity, vertical и catalog context version;
- OpenAI output не может сохранить выдуманные Evidence IDs; без Evidence confidence снижается;
- отдельный semantic benchmark содержит 200 размеченных RU / UZ Latin / UZ Cyrillic
  сценариев; внутренние precision/recall/intent/B2B gates проходят;
- benchmark всё ещё внутренний и после исправлений не является unseen production sample.
- добавлен отдельный `challenge:v1`: 36 сложных RU / UZ Latin / UZ Cyrillic фраз;
  первый baseline честно показал 83,9% precision и 50% false HOT среди negative cases;
- после точечных исправлений negation/job/word-boundary/`ta`/B2B morphology challenge даёт
  100% precision/recall, 97,2% intent, 100% role и 0% false HOT;
- оставшийся mismatch не скрыт и отображается в `/system`; challenge использовался
  для исправлений и поэтому не называется unseen production sample;
- текущий offline gate challenge-этапа: **210 tests passed**, Ruff и compileall чистые;
  live Instagram/OpenAI и пересчёт сохранённых лидов не запускались;

## Master Phase B — Lead Intelligence V3 calibration

- сохранён один production scorer; второй параллельный алгоритм не создавался;
- primary intent теперь выбирается по смысловой специфичности: DELIVERY/SIZE/COLOR/
  CATALOG важнее общих `qancha`, `bormi`, `есть?`;
- buyer role отделена от primary intent: B2B/HoReCa и designer-контекст больше не
  перезаписывают PRICE, DELIVERY, CATALOG или AVAILABILITY общим значением BUY;
- ценовое возражение теперь сохраняется в risk flags, реально уменьшает итоговый priority
  и переключает рекомендацию на уточнение бюджета без выдуманной скидки;
- benchmark поддерживает точные intent labels для отдельных фраз внутри role-группы,
  поэтому качество больше не маскируется одним общим label для всей группы;
- job-seeking и unrelated-media сигналы разделены: они больше не смешиваются в общий SPAM;
- quantity извлекается до общих BUY-маркеров, но явное «хочу заказать/сотиб олмоқчиман»
  остаётся BUY;
- расширены RU/UZ business, designer, negation и reaction границы без изменения
  evidence-first history/decay/multi-competitor логики;
- новый статический benchmark: **200 смысловых фраз**, не варианты регистра и punctuation;
- внутренний результат: lead precision **100%**, recall **100%**, intent accuracy **100%**,
  buyer-role accuracy **100%**, B2B precision **100%**, HOT false-positive **0%**;
- это calibration score на проверяемом fixture, не заявление о реальной production accuracy;
  unseen offline sample и controlled live pilot остаются `BLOCKED`;
- offline gate после role/intent decoupling: **208 tests passed**, Ruff и
  compileall чистые; Instagram/OpenAI live-вызовы не выполнялись;
- первоначальный offline gate Master Phase B: **191 tests passed**; сохранён как
  историческая контрольная точка.

## Master Phase C — Audience Engine V3 hardening

> Историческая контрольная точка. Активная модель и имена аудиторий заменены
> управляемым реестром Audience Intelligence V4 выше.

- добавлены идемпотентные `InterestEvidence`, связанные с реальными Evidence/PublicSignal;
- `ContactInterestProfile` хранит decayed score, confidence, first/last seen, source count и Evidence IDs;
- реакции и некоммерческий шум не создают interest evidence и не усиливают multi-competitor;
- membership хранит структурированные причины, реальные Evidence IDs, expiry и engine version;
- `OutcomeDNA` использует только признаки, наблюдавшиеся до `won_at`, без leakage статуса WON;
- интерфейс сегмента показывает менеджеру «почему контакт здесь»;
- на этом этапе был удалён дубль `multi-competitor-2`; последующий V4 также вывел из
  эксплуатации `comparison-shoppers` в пользу `furniture-comparison`;
- исторический `high-intent-b2c` был ограничен 30 днями; в V4 его заменил
  `furniture-high-intent` на текущем decayed intent score;
- пустые и `UNKNOWN` профили больше не считаются похожими; результат similarity не
  возвращается без наблюдаемого коммерческого признака;
- similarity учитывает товар, intent и его последовательность, recency, buyer role,
  B2B/B2C, quantity band, vertical и пересечение конкурентов; менеджер получает причины;
- миграция `f3b9d7a61c20` применена к рабочей БД, Alembic schema check чистый;
- полная цепочка Alembic подтверждена отдельно на новой пустой SQLite БД;
- текущая рабочая БД: 16 evidence-first interest profiles, 650 уникальных memberships, дубликатов нет;
- полный offline gate: **193 tests passed**, Ruff и compileall чистые;
- audience golden/eval пока недостаточен, поэтому production/pilot ready остаётся `No`;
  paid/live recalculation не запускался.

## Master Phase D — Artificial Rattan Vertical V2 hardening

- добавлен строгий `RattanTaxonomyService`: без явного rattan-контекста обычные столы,
  кресла и мебель остаются в вертикали `FURNITURE`;
- сырьё (`RAW_RATTAN`, бухта, кг, плоский/круглый/полукруглый профиль) отделено от
  готовой ротанговой мебели и ролей рынка;
- одно слово `ротанг/rattan` без признаков товара, сырья или роли больше не создаёт
  выдуманный `RAW_MATERIAL`: сохраняется честный слой `NONE` до появления Evidence;
- натуральный ротанг явно исключён из вертикали искусственного ротанга;
- `vertical` проходит через Competitor, PublicSignal, Evidence, Lead и AudienceSegment;
- сохранённые записи перестраиваются идемпотентно, Evidence остаётся источником
  доказательств, а BusinessEntity получает объединение наблюдавшихся вертикалей;
- отдельный `/rattan` workspace показывает только реальные записи БД и честно сообщает,
  что источник поиска выключен; demo-компании не создаются;
- добавлены отдельные rattan-аудитории для сырья, готовой мебели, опта и высокой ценности;
- migration `a6d4e2c91f30` проверена на рабочей и новой пустой SQLite БД;
- golden fixture: 30 RU/UZ/EN сценариев, включая неопределённый и натуральный ротанг,
  отрицательные примеры и ложные совпадения по «кг», кабелю и обычной мебели;
- рабочая БД: 22 доказательных rattan-сигнала и 1 подтверждённая компания;
- integrity gate: 0 дублей и 0 вертикальных рассогласований Lead/Evidence/PublicSignal;
- полный offline gate: **194 tests passed**, Ruff и compileall чистые;
- live discovery и внешний pilot не запускались, поэтому production ready остаётся `No`.

## Master Phase E — Unit Economics

- старый in-memory калькулятор удалён: экономика теперь строится из `CostEvent`,
  `PublicSignal`, `Lead` и фактических WON-сделок;
- доступны периоды 24 часа, 7 и 30 дней, разрезы по provider, vertical и competitor source;
- рассчитываются Cost per Signal, Commercial Signal, Lead, HOT, B2B и WON;
- если хотя бы один cost event не имеет тарифа, производные стоимости показываются как
  неизвестные, а не как ложный `$0` или неполная точная цифра;
- Instagram wrapper сохраняет нормализованный `source_account`, чтобы новые расходы можно
  было связать с конкурентом без прямой зависимости provider-адаптера от БД;
- `/analytics` стал рабочим экраном экономики и заменил N+1 расчёт эффективности источников;
- ROI не рассчитывается: расходы сейчас в USD, выручка в UZS, versioned FX policy отсутствует;
- Gross Profit не рассчитывается до появления подтверждённого COGS проданной позиции;
- полный offline gate: **197 tests passed**, Ruff и compileall чистые;
- live billing reconciliation и платные вызовы не выполнялись, production ready остаётся `No`.

## Master Phase 5 — Confirmed Catalog and grounded Next Best Action

- создана таблица products и отдельная Alembic migration; каталог стал частью БД;
- seed содержит ровно 10 подтверждённых позиций из master specification, без
  дополнительных демонстрационных товаров;
- SKU, stock, COGS, colors и category не угадываются: до ручной проверки они остаются
  NULL/UNCONFIRMED;
- startup sync идемпотентен и не перезаписывает подтверждения менеджера;
- экран /catalog показывает происхождение данных, точные цены/размеры/нагрузку и честные
  unknown states; менеджер может подтвердить category, stock и COGS;
- Next Best Action получает только сохранённые Product records и не обещает скидку,
  наличие, срок доставки, оптовую цену, 3D-файлы или агентское вознаграждение;
- при отсутствии подтверждённого совпадения менеджер получает безопасное действие:
  уточнить модель/параметры и проверить наличие перед предложением;
- удалён hardcoded AgentSessionAssistant с fake HOT 91, fake evidence и fake SKU;
  /api/agent/query теперь использует `AgentSessionService` с DB-backed read tools;
- контракт и ограничения описаны в docs/PRODUCT_CATALOG.md;
- полный offline gate: **205 tests passed**, Ruff и compileall чистые;
- live/paid вызовы не выполнялись, maturity остаётся OFFLINE.

## Master Phase F — Discovery Center and Diff Engine

- кандидаты больше не смешаны с действующими конкурентами: единая очередь проверки
  находится на `/discovery`, а `/competitors` показывает только компании в радаре;
- CSV/XLSX импорт выполняется локально, ограничен 5 МБ и 2 000 строками и не вызывает
  provider API, Telegram или OpenAI;
- identity resolution использует нормализованный Instagram, hostname сайта и затем
  Unicode-нормализованное название; canonical key защищён уникальным индексом;
- повтор одинаковой строки обновляет только `last_seen_at`, не создаёт кандидата или diff;
- snapshot fingerprint и неизменяемый `MarketCandidateDiff` фиксируют NEW, UPDATED,
  PRICE_CHANGED, STOCK_CHANGED и ROLE_CHANGED;
- REVIEWED/REJECTED — бесплатные состояния проверки; перевод в мониторинг требует
  подтверждённого публичного Instagram и создаёт конкурента на паузе;
- небезопасные URL схемы отбрасываются, импорт ограничен публичными бизнес-данными;
- автоматические Google/2GIS/OSM/marketplace jobs, AI query expansion и paid enrichment
  намеренно не запущены до отдельного budget/confirmation gate;
- контракт и ограничения описаны в `docs/DISCOVERY_CENTER.md`;
- полный offline gate: **202 tests passed**, Ruff, compileall и fresh/repeated Alembic чистые;
- live/paid discovery не выполнялся, production ready остаётся `No`.

## Phase F — Deterministic Offline Pilot

- добавлен network-free runner `python -m scripts.run_offline_pilot`;
- 60 вручную размеченных корневых сценариев разворачиваются в 600 вариантов регистра,
  пробелов, пунктуации и emoji;
- текущий robustness replay: lead precision/recall/intent accuracy 100%, rattan
  precision/recall/layer accuracy 100%;
- первый ingestion создаёт ровно 600 Comment/PublicSignal/Evidence, идентичный повтор —
  0 новых записей и 0 дублей;
- pilot выявил и помог исправить ложные пропуски коммерческого CTA `+?`, `+!`,
  `+ 🙏`, `+...`, не ослабляя правило для плюса без явного CTA в подписи;
- результат и ограничения задокументированы в `docs/OFFLINE_PILOT_REPORT.md`;
- это robustness-набор из 60 независимых корней, а не 600 независимо собранных
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

Активная программа завершения закрыла **Stages 0–3**: truth/baseline, schema contract,
production web security и workflow integrity. Сейчас выполняется
**Stage 4 — Catalog → Offer → Demand Gap**. Далее: Unit Economics, независимые
quality gates, grounded Agent/MCP, UI/Telegram hardening и deployment readiness.

Стадии и утверждённый порядок отражены в актуальном `ROADMAP.md`; старые Master/V6-разделы
ниже сохранены только как исторические контрольные точки.

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

- UI-hardening: мобильная навигация автоматически показывает активный раздел, широкие таблицы
  получили подсказку и клавиатурный фокус, строки клиентов открываются по Enter/Space, а диалог
  подтверждения возвращает фокус и закрывается по Escape.
- Полосы аналитической воронки теперь нормализуются относительно максимального этапа, поэтому
  не показывают одинаковые 100% для любых значений выше восьми.
- Все 15 основных маршрутов проверены при мобильной ширине: горизонтального переполнения и
  ошибок консоли нет; rattan-сигналы читаются карточками без горизонтальной прокрутки.
- Модерация B2B-открытий больше не использует отдельный inline JavaScript и `alert`: действия
  идут через общий JSON-клиент, требуют подтверждения и показывают единый toast результата.
- Ротанговая вертикаль больше не считает реакции и незавершённый анализ покупательским спросом:
  продуктовая таксономия и список сигналов строятся только по подтверждённым lead-статусам,
  а число исключённых записей показано отдельно.

- Python compileall: passed.
- `ruff check app scripts`: passed.
- Alembic head/current: `d6b1e4f92a50`; `alembic check` не выявляет новых операций.
- Проверка целостности: passed; дубли по comment ID, post URL, lead/comment, deal/lead и
  notification target отсутствуют.
- Исходные данные сохранены: 25 контактов, 12 постов и 28 комментариев. После локальной
  квалификации история расширилась до 53 неизменяемых событий и 28 результатов разбора.
- Результат синхронизации: **16 competitors / 1 active / 24 открытых market candidates**.
- Повторная синхронизация каталога дважды создала `0` конкурентов и `0` кандидатов.
- Локальный web smoke: `/health` и `/` успешны; `/api/scan` возвращает блокировку `409`.
- актуальный полный `pytest`: **232 passed**; тесты блокируют внешнюю сеть и не обращаются
  к Instagram/OpenAI, поэтому API-токены не расходуются.
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

Текущая цель — Catalog → Offer → Demand Gap: подтверждённые свойства и импорт каталога,
объяснимое ранжирование, sale snapshot и измерение непокрытого наблюдаемого спроса.

Live-поиск и все платные интеграции остаются выключенными до отдельного controlled pilot.

Полная дорожная карта: `ROADMAP.md`.
