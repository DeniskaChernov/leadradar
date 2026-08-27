# Lead Radar V6 — Data Integrity Audit Report

## 1. Data Integrity Verification Script
The project features an automated integrity check script (`scripts/check_data_integrity.py`) executing 17 verification assertions:

1. `duplicate comment IDs: 0`
2. `duplicate post URLs: 0`
3. `duplicate lead comments: 0`
4. `duplicate public signal comments: 0`
5. `duplicate public signal dedupe keys: 0`
6. `duplicate public signal external identities: 0`
7. `duplicate business canonical keys: 0`
8. `duplicate business aliases: 0`
9. `duplicate evidence keys: 0`
10. `duplicate contact intelligence profiles: 0`
11. `duplicate audience memberships: 0`
12. `duplicate deal leads: 0`
13. `duplicate notification targets: 0`
14. `duplicate notification idempotency keys: 0`
15. `duplicate significant changes per lead: 0`
16. `duplicate significant change notification targets: 0`
17. `duplicate significant change notification idempotency keys: 0`

Result: **All 17 checks passed (OK)**.

## 2. Concurrency & Idempotency Rules
- **Signal Deduplication**: `ContactService.persist_signal()` uses unique constraint `uq_comments_platform_comment_id` and unique `external_id` / `dedupe_key` on `PublicSignal`.
- **Notification Outbox**: `notification_logs` table uses worker lease lock (`lease_token`, `lease_expires_at`) to ensure single-worker claim and prevent duplicate Telegram messages.
- **Entity Resolution**: `BusinessEntity` merging requires strong evidence (matching Google Place ID, confirmed public phone + domain relation). Fuzzy name similarity alone does NOT merge distinct companies or people.

## 3. Database Migration Integrity
- Alembic migrations (`alembic/versions/`) form a clean single-head linear chain ending at `b1c2d3e4f5a6` (`opening_signals`).
- Tested on both empty database initialization and existing database copies (`alembic upgrade head`).
