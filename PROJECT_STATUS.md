# Lead Radar Project Status

## Current stage

Stage 8/9 complete — moving to integration checks, hardening, and documentation.

## Completed

- Empty repository inspected.
- Official OpenAI, ScrapeCreators, and Bright Data API documentation reviewed.
- Environment contract and secret-safe Git exclusions created.
- SQLAlchemy async database foundation and complete MVP entity model created.
- Initial Alembic migration generated and applied to SQLite successfully.
- Python 3.12 virtual environment and project dependencies installed.
- Contact/post/comment/event repositories and transactional signal persistence added.
- Mock, ScrapeCreators, Bright Data, and automatic fallback providers implemented.
- Provider normalization follows current official documented fields.
- OpenAI Responses API structured Pydantic scoring and AI_PENDING recovery added.
- Lead/AIFeedback creation commits before notification.
- Baseline-aware polling skips unchanged posts and retries failed comment synchronizations.
- Telegram long polling commands, HOT cards, access checks, and inline callbacks added.
- Atomic manager assignment, NOT_LEAD feedback, and deal WON/LOST FSM implemented.
- Telegram notification attempts and message IDs persist in the database.

## In progress

- Integration checker, acceptance hardening, Docker/Railway preparation, and documentation.

## Next

- Telegram workflows, deals, integration checker, hardening, and user documentation.

## Known issues

- Real external integrations are not yet validated with local API keys.

## Tests

- 12 tests pass, including manager assignment/double-assignment protection, NOT_LEAD,
  deal WON, and deal LOST.
- `python -m app.main --once` completes a mock baseline cycle without a stack trace.
- Alembic upgrade to the initial schema passed.
- Ruff passes for all current files.

## How to run

Not ready for application startup yet.

## Last verified commit

22f3d89 (Stage 1 scaffold)
