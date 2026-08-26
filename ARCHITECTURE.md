# Lead Radar Architecture

## Core rule

SQLite/PostgreSQL is the source of truth. Telegram is an operational interface, never storage.

```text
InstagramProvider (Mock / ScrapeCreators -> Bright Data fallback)
        |
        v
InstagramMonitor
        |
        v
transaction 1: Competitor + Post + Contact + Comment + COMMENT_FOUND
        |
        v
OpenAI structured analysis (or durable AI_PENDING)
        |
        v
transaction 2: Lead + LEAD_CREATED + AIFeedback
        |
        v
TelegramLeadNotifier + durable NotificationLog
        |
        v
atomic manager assignment -> deal WON/LOST -> immutable events + AI feedback
```

## Boundaries

- `app/providers`: public Instagram transport and provider-specific normalization only.
- `app/db`: SQLAlchemy models, repositories, async session factory, and Alembic migrations.
- `app/services`: ingestion, scoring, monitoring, notification, and workflow business rules.
- `app/bot`: aiogram commands, callbacks, and FSM dialogue; no provider access.
- `app/schemas`: provider-neutral Pydantic contracts and OpenAI structured output model.

## Idempotency and failure handling

- `comments(platform, platform_comment_id)` is unique across all providers.
- `leads.comment_id` is unique, so a signal can produce at most one lead.
- notification `(lead_id, chat_id)` is unique and records PENDING/SENT/FAILED.
- contact/comment/event commit happens before AI.
- lead/feedback/event commit happens before Telegram.
- provider requests have bounded exponential backoff; ScrapeCreators failures activate Bright Data.
- `comments_fetched_count` advances only after successful comment processing, so a failed fetch is
  retried even when Instagram's public `comments_count` remains unchanged.
- AI failures create `AI_PENDING`; later polling cycles retry analysis.

## Database portability

Repositories use SQLAlchemy expressions rather than SQLite-specific SQL. `DATABASE_URL` accepts
local `sqlite+aiosqlite://` and Railway-style `postgres://`/`postgresql://` URLs, normalized to
`postgresql+asyncpg://` at startup.

