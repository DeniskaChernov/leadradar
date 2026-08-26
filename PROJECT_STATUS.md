# Lead Radar Project Status

## Current stage

Local MVP complete and ready for the first credentialed integration test.

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
- Telegram deal workflow for WON/LOST outcomes and feedback dataset updates.
- Independent Database/Telegram/OpenAI/ScrapeCreators/Bright Data integration checker.
- Dockerfile, Railway configuration, architecture notes, and non-developer setup guide.

## In progress

- None in local code. The app is ready to build its first real provider baseline.

## Next

1. Create local `.env` from `.env.example` and fill secrets locally.
2. Run `python -m alembic upgrade head`.
3. Run `python -m scripts.check_integrations`.
4. Start with `python -m app.main`, use `/start`, then configure admin IDs.
5. Validate mock mode before switching `INSTAGRAM_PROVIDER` to `scrapecreators`.

## Known issues

- Bright Data's synchronous Comments by URL endpoint returns the latest 15 comments per request.
- FAILED Telegram notifications are durable but have no separate automatic retry worker; the lead
  remains available through `/hot`.
- Telegram FSM state is in memory and is reset by process restart.
- Docker build was not executed because Docker is not installed on the verification machine.
- SQLite and a single process are intentional local-MVP constraints.

## Tests

- `python -m pytest -q`: 17 passed.
- `ruff check .`: passed.
- `python -m scripts.check_integrations`: Database, Telegram, OpenAI, ScrapeCreators, and Bright
  Data all OK with local credentials on 2026-08-26.
- `python -m app.main --once`: completed mock polling without a stack trace.
- `python -m pip check`: passed; no broken requirements.
- `alembic check`: passed; no missing migration operations.

Covered behavior includes contact upsert, cross-provider comment deduplication, provider
normalization/fallback, lead creation, Structured Output parsing, HOT threshold, immutable events,
baseline, unchanged-post skipping, AI retry, manager assignment, double-assignment protection,
provider-change baseline reset, NOT_LEAD, deal WON/LOST, and full mock HOT-to-WON acceptance flow.

## How to run

```bash
python -m app.main
```

Full setup commands are in `README.md`.

## Last verified commit

`HEAD` (final local MVP commit; verify with `git log -1 --oneline`).
