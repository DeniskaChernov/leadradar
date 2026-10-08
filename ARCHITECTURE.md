# Lead Radar V3.2 — архитектура

## Главный принцип

**База данных — источник истины.** Telegram, Mini App и AI работают поверх уже сохранённых данных.

```text
Public Instagram
      ↓
InstagramProvider abstraction
      ├─ Replay / Mock          ← разработка без расходов
      └─ ScrapeCreators         ← live primary
             ↓ failure
         Bright Data            ← live fallback
      ↓
Cost guards
      ├─ global live unlock
      ├─ daily limit
      └─ per-scan limit
      ↓
InstagramMonitor
      ↓
Post/Reel + Contact + Comment
      ↓ COMMIT
Local rule classifier
      ├─ уверенный сигнал → Lead / NOT_LEAD
      └─ неоднозначный → AI_PENDING
             ↓ explicit live unlock only
          OpenAI + cache
             ↓
Lead + AIFeedback
      ↓ COMMIT
┌────────────────────┬─────────────────────────┐
│ Telegram alerts    │ Mini App / CRM          │
│ HOT / quick action │ search / funnel / tasks │
└────────────────────┴─────────────────────────┘
             ↓
Manager actions / qualification / deal
             ↓
contact_events + ai_feedback + revenue outcome
```

## Domain model

### Contact

Один человек. Instagram user ID предпочтительнее username. Если ID недоступен, используется
нормализованный username. Карточка хранит CRM-квалификацию и менеджера.

### Signal / Comment

Публичное проявление интереса. Один Contact может иметь много сигналов у разных конкурентов.

### Lead

Коммерческая интерпретация конкретного Signal. Статусы ведут человека по воронке.

### Deal

Денежная возможность. Итог WON/LOST возвращается в `ai_feedback`.

### ContactEvent

Immutable timeline: комментарий найден, лид создан, назначен менеджер, заметка, ответ клиента,
следующий контакт, предложение, сделка, продажа/отказ.

## Cost-safe AI

AI имеет три слоя:

1. `RuleBasedLeadAnalyzer` — локально, 0 токенов;
2. `AI_PENDING` — неоднозначный сигнал ждёт осознанного решения;
3. `BudgetedCachedOpenAIAnalyzer` — только после double unlock, с daily budget и cache.

Кнопка локального исторического разбора в Mini App создаёт отдельный analyzer без OpenAI. Поэтому
она не может случайно потратить токены даже при production-настройках.

## Cost-safe Instagram

Live Instagram доступен только если одновременно выполнены условия:

```text
INSTAGRAM_PROVIDER = live provider
INSTAGRAM_LIVE_CALLS_ENABLED = true
EXTERNAL_LIVE_UNLOCK = ALLOW_EXTERNAL_CALLS
```

Дополнительно:

- дневной лимит `INSTAGRAM_DAILY_REQUEST_LIMIT`;
- предел одного scan `INSTAGRAM_MAX_UNITS_PER_SCAN`;
- scheduled live scans по умолчанию запрещены;
- ручной live scan требует отдельного подтверждения;
- fallback использует тот же scan budget.

## Incremental comments sync

`Post.comments_count` — remote count из Reel metadata.

`comments_fetched_count` — сколько комментариев реально сохранено/получено.

`last_synced_remote_count` — remote count в момент последнего comments fetch.

`coverage_status`:

- `FULL` — полнота доказана;
- `PARTIAL` — API/page-limit не дал полную историю;
- `LATEST_ONLY` — контракт provider даёт только последние комментарии;
- `UNKNOWN` — полнота не доказана.

ScrapeCreators идёт по cursor и не прекращает обход только из-за знакомого
`comment_id`: API не гарантирует хронологический порядок. Baseline и incremental
page limits задаются отдельно. Позиция добора сохраняется с provider identity;
проверка начала списка новых комментариев не уничтожает исторический cursor.
Повторный cursor/цикл завершает batch как PARTIAL с сохранёнными комментариями.
Список публикаций источника пока использует первую страницу; вложенные публичные
ответы не раскрываются дополнительным запросом.

## Mini App

Backend: FastAPI + Jinja, без Node build step для локального MVP.

Основные read-модули: `app/web/queries.py`.

Business actions проходят через services; templates не обращаются к providers напрямую.

Разделы:

- Обзор;
- Радар;
- Лиды;
- Клиенты;
- Задачи;
- Сделки;
- Аналитика;
- Конкуренты / карта рынка;
- Развитие;
- Система.

## Telegram Mini App auth

В локальном режиме `WEB_AUTH_ENABLED=false` и web bind по умолчанию `127.0.0.1`.

Перед публичным Railway deploy:

- `WEB_AUTH_ENABLED=true`;
- сервер валидирует Telegram `initData`;
- создаётся signed session cookie;
- доступ ограничивается разрешёнными Telegram ID.

## Idempotency

Критические unique constraints:

- Contact: platform + external identity;
- Post: platform + post ID / URL;
- Comment: platform + comment ID;
- Lead: один на Comment;
- Deal: один на Lead;
- Notification: один `(lead, chat)`.

Повторный polling, restart и provider fallback не должны создавать дубли.

## Local → Railway

Сейчас:

```text
single process
SQLite
FastAPI CRM (web-only)
Cloudflare Quick Tunnel -> включённый Windows-компьютер
```

Позже:

```text
Railway
PostgreSQL
HTTPS
Telegram Mini App auth
```

При нескольких application instances scheduler/outbox/locks нужно вынести в shared coordination
layer (Redis/queue/advisory locks). До этого масштабировать процесс горизонтально нельзя.

Файловая SQLite защищена DatabaseRuntimeLock до стартовых операций и на весь
процесс; restore использует ту же блокировку. Backup — SQLite Online Backup API
с проверкой снимка и атомарной публикацией. Lifecycle receipt фиксирует PID/run/build,
heartbeat и завершение без текста исключения/секретов. Прошлый RUNNING означает
отсутствие финального receipt, а не установленную причину аварии. PostgreSQL имеет
диагностику в памяти; распределённое владение и cutover остаются отдельными задачами.
Актуальный [реестр возможностей](docs/CAPABILITY_REGISTER_2026-10-08.md).


## Market intelligence V3.2

`competitors` — проверенные аккаунты, которые можно включить в monitor scheduler.

`market_candidates` — карта найденных компаний, чей текущий Instagram username ещё требует
подтверждения. Это разделение важно: market discovery не должен автоматически создавать платный
API-трафик.

`MarketIntelligenceService.sync_catalog()` работает только с нашей БД, idempotent и вызывается при
старте. Он не перезаписывает пользовательские active/tier настройки существующего конкурента.

InstagramMonitor уже загружает активные competitors динамически из БД, поэтому включение/пауза в
Mini App действует без restart. Значение `COMPETITORS` остаётся только bootstrap-механизмом.

Cross-competitor history используется как ограниченный дополнительный сигнал lead scoring: человек,
который сравнивает нескольких продавцов, получает больший приоритет, но сама история не может
сделать слабый комментарий HOT без покупательского intent.
