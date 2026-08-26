# Lead Radar Project Status

## Current stage

Stage 3/4 — AI lead scoring and Instagram monitoring orchestration.

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

## In progress

- AI scoring, lead creation, baseline-aware polling, and notification orchestration.

## Next

- Telegram workflows, deals, integration checker, hardening, and user documentation.

## Known issues

- Real external integrations are not yet validated with local API keys.

## Tests

- 5 tests pass: contact upsert, comment dedup, baseline persistence, provider normalization,
  and provider fallback.
- Alembic upgrade to the initial schema passed.
- Ruff passes for all current files.

## How to run

Not ready for application startup yet.

## Last verified commit

22f3d89 (Stage 1 scaffold)
