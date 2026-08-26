# Lead Radar Engineering Rules

- The database is the source of truth. Persist and commit before any Telegram action.
- Every ingestion and workflow operation must be idempotent.
- Never commit secrets or put API tokens in source code. `.env` stays local and ignored.
- Process public Instagram data only. Never fetch private/hidden user data, phone numbers, or email addresses.
- Provider APIs are isolated behind the `InstagramProvider` adapter interface.
- Telegram handlers must never call provider APIs directly.
- Business rules live in services; handlers coordinate user interaction only.
- Important behavior changes require automated tests.
- Preserve immutable contact history through `contact_events`.
- Update `PROJECT_STATUS.md` after each substantial stage and keep it aligned with verified code.
- Run `pytest` and `ruff check .` before declaring a stage complete.

