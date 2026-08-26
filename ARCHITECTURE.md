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

- `contacts(platform, platform_user_id/normalized_username)` is unique.
- `posts(platform, platform_post_id)` and `posts(platform, url)` are unique, covering providers
  that expose different IDs for the same Reel.
- `comments(platform, platform_comment_id)` is unique across all providers.
- `leads.comment_id` is unique, so a signal can produce at most one lead.
- `deals.lead_id` is unique, so simultaneous button presses cannot create two deals.
- notification `(lead_id, chat_id)` is unique and uses a durable
  PENDING -> PROCESSING -> SENT/FAILED outbox state machine.
- contact/comment/event commit happens before AI.
- lead/feedback/event commit happens before Telegram.
- provider requests have bounded exponential backoff; ScrapeCreators failures activate Bright Data.
- `comments_fetched_count` advances only after successful comment processing, so a failed fetch is
  retried even when Instagram's public `comments_count` remains unchanged.
- `comments_checked_at` forces a periodic full refresh even when the public count does not change;
  database constraints make every repeated refresh idempotent.
- competitor baseline records the provider identity, so changing from mock to a real adapter builds
  a fresh no-notification baseline rather than treating existing comments as new.
- AI failures create `AI_PENDING`; later polling cycles retry analysis.
- startup applies pending Alembic migrations before polling begins; SQLite foreign-key enforcement
  is enabled for every application connection.

## Database portability

Repositories use SQLAlchemy expressions rather than SQLite-specific SQL. `DATABASE_URL` accepts
local `sqlite+aiosqlite://` and Railway-style `postgres://`/`postgresql://` URLs, normalized to
`postgresql+asyncpg://` at startup.
