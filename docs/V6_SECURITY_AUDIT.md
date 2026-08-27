# Lead Radar V6 — Security & Privacy Audit Report

## 1. Secrets & Credentials Audit
- **Git Tracking**: Verified `.env` is listed in `.gitignore` and is NOT tracked by Git (`git ls-files .env` returned 0 results).
- **Environment Variables**: `.env.example` contains place-holder keys without exposing actual production secrets.
- **Runtime Safety**: API keys (`OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `SCRAPECREATORS_API_KEY`, `BRIGHTDATA_API_KEY`) are loaded via `pydantic-settings` (`app/config.py`) and are never exposed in browser API responses or client logs.

## 2. Authentication & Authorization
- **Telegram WebApp Authentication**: `app/web/auth.py` validates Telegram `initData` using HMAC-SHA256 with the bot token secret key. Enforces max token age (`telegram_init_data_max_age_seconds`).
- **Dev Auth Bypass**: In local development (`WEB_AUTH_ENABLED=false`), auth checks pass gracefully for testing, but in production (`WEB_AUTH_ENABLED=true`), invalid signatures raise `401 Unauthorized`.

## 3. Input Sanitization & XSS Prevention
- **Jinja2 SSR Templates**: Auto-escaping is active across HTML templates. Public Instagram comment texts are rendered safely inside standard tags (`{{ comment.text }}`).
- **JSON Outputs**: Web API endpoints serialize responses via FastAPI's `JSONResponse`, avoiding raw inline script execution.

## 4. Privacy & Data Boundaries
- **Public Data Only**: System processes public Instagram comments, captions, and publicly visible business information.
- **No Hidden PII Extraction**: No scraping of private Instagram profiles, DMs, hidden emails, or unlisted phone numbers.
- **Export Privacy**:
  - `dry_run=True` returns SHA-256 privacy hashes only.
  - Customer list exports strictly require `ExportEligibility.FIRST_PARTY_ELIGIBLE` (verified phone or confirmed qualification).
  - No protected or sensitive traits (religion, health, politics, ethnicity) are collected or used in audience creation.

## 5. Agent & Tool Safety (Human-in-the-Loop)
- **Read vs Write Isolation**: Read-only tools execute automatically for context retrieval.
- **Guarded Write Actions**: Actions that spend budget (Meta campaign creation), modify critical status (marking deals WON/LOST), or execute destructive operations strictly require explicit human approval.
