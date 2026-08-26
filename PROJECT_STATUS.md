# Lead Radar Project Status

## Current stage

Hardened local MVP complete and verified with the credentialed real provider.

## Completed

- Modular Python 3.12 application scaffold and secret-safe environment contract.
- Async SQLAlchemy models for competitors, posts, contacts, comments, immutable contact events,
  leads, deals, AI feedback, and Telegram notification logs.
- Alembic initial schema plus fetched-comment synchronization migration.
- Database-first, idempotent comment ingestion and contact upsert.
- Mock, ScrapeCreators, Bright Data, and ScrapeCreators-to-Bright-Data fallback providers.
- Provider-scoped baseline behavior and comment-count optimization with failure-safe retry state.
- OpenAI Responses API Structured Outputs through a Pydantic schema.
- Durable `AI_PENDING` leads with automatic retry on later polling cycles.
- HOT threshold, previous-signal context, and 14-day repeat-interest calculation.
- aiogram long polling with `/start`, `/status`, `/stats`, `/hot`, and `/competitors`.
- Durable HOT notification results, atomic manager assignment, and NOT_LEAD feedback.
- Atomic Telegram outbox claiming, bounded retry state, and startup reconciliation of unsent HOT
  leads without duplicate `(lead, chat)` deliveries.
- Unique database identities for provider-independent Reel URLs, comments, leads, deals, and
  notification targets.
- Periodic forced comment refresh to detect new comments even when the provider count is unchanged.
- Automatic Alembic migrations on application startup and enforced SQLite foreign keys.
- Standalone `python -m scripts.check_data_integrity` duplicate audit.
- Telegram deal workflow for WON/LOST outcomes and feedback dataset updates.
- Independent Database/Telegram/OpenAI/ScrapeCreators/Bright Data integration checker.
- Dockerfile, Railway configuration, architecture notes, and non-developer setup guide.

## In progress

- None in local code. The app is ready to build its first real provider baseline.

## Next

1. Keep one application process running with `python -m app.main`.
2. Use Telegram `/status`, `/stats`, and `/hot` for daily operation.
3. Run `python -m scripts.check_data_integrity` whenever an explicit duplicate audit is wanted.

## Known issues

- Bright Data's synchronous Comments by URL endpoint returns the latest 15 comments per request.
- A process crash in the ambiguous moment after Telegram accepted a message but before the local
  SENT commit leaves the outbox item in PROCESSING. It is not resent automatically because doing so
  could duplicate the Telegram message; the lead remains available through `/hot`.
- Telegram FSM state is in memory and is reset by process restart.
- Docker build was not executed because Docker is not installed on the verification machine.
- SQLite and a single process are intentional local-MVP constraints.

## Tests

- `python -m pytest -q`: 21 passed.
- `ruff check .`: passed.
- `python -m scripts.check_integrations`: Database, Telegram, OpenAI, ScrapeCreators, and Bright
  Data all OK with local credentials on 2026-08-26.
- `python -m app.main --once`: completed mock polling without a stack trace.
- Two consecutive real ScrapeCreators cycles on 2026-08-26: first safely re-read 27 comments with
  `comments_created=0`; second used `comment_requests=0`; both finished with `errors=0`.
- `python -m scripts.check_data_integrity`: all five duplicate checks passed with zero duplicates.
- `python -m pip check`: passed; no broken requirements.
- `alembic check`: passed; no missing migration operations.

Covered behavior includes contact upsert, cross-provider comment deduplication, provider
normalization/fallback, lead creation, Structured Output parsing, HOT threshold, immutable events,
baseline, unchanged-post skipping, AI retry, manager assignment, double-assignment protection,
provider-change baseline reset, forced refresh with unchanged counts, cross-provider Reel identity,
concurrent notification delivery, NOT_LEAD, deal WON/LOST, SQLite foreign keys, and full mock
HOT-to-WON acceptance flow.

## How to run

```bash
python -m app.main
```

Full setup commands are in `README.md`.

## Last verified commit

Current HEAD (`feat: harden idempotent lead processing`).
