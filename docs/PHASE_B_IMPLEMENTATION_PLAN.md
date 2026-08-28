# Phase B Implementation Plan — AI Idempotency and Atomic Budget Safety

## Current race conditions

- The durable `AIRequest` unique key and atomic claim already prevent the common concurrent
  duplicate-call path, but lease duration and maximum attempts are hard-coded rather than
  configuration-backed.
- A stale claim can be taken over, but failure classification and conservative unknown-billing
  handling are incomplete.
- `ExternalBudgetReservation` serializes SQLite reservations with `BEGIN IMMEDIATE`, but it lacks
  a stable reservation key, worker identity and explicit release/actual-usage audit fields.
- `ExternalUsage` has no unique source reservation key, so a future finalize regression could
  create duplicate historical usage even though the current compare-and-set usually prevents it.
- Startup recovery and the requested AI/budget diagnostic counts are not implemented as a
  dedicated service.

## Required schema changes

- Make `AIRequest.analysis_version` an explicit string contract version (`3.0`).
- Add prompt/schema versions, completion timestamp and structured error type/message.
- Add `ExternalBudgetReservation.reservation_key`, worker identity, reserved/released timestamps,
  actual units/cost and details.
- Add `ExternalUsage.idempotency_key` so one finalized reservation creates at most one usage row.
- Preserve existing columns and backfill legacy rows without deleting data.

## Transaction strategy

1. Compute a canonical semantic fingerprint outside the transaction.
2. Insert `AIRequest` with the unique lead/version/fingerprint key and a random claim token.
3. On conflict, atomically return cached success, reject a live lease, or take over an expired
   retryable claim while enforcing `AI_REQUEST_MAX_ATTEMPTS`.
4. Reserve budget in a committed DB transaction before any external call.
5. Persist AI success under the exact claim token before finalizing the reservation.
6. Finalize reservation and create `ExternalUsage` with the reservation idempotency key in one
   transaction. Compare-and-set transitions make repeats no-ops.

## SQLite limitations

SQLite has no row-level `SELECT FOR UPDATE`. Budget check plus reservation therefore starts with
`BEGIN IMMEDIATE`, acquiring the database write lock before reading totals. This serializes
independent processes, not only asyncio tasks. Lock contention remains possible and should surface
as a safe failure rather than bypassing the budget.

## Future PostgreSQL compatibility

Domain services use SQLAlchemy transactions and compare-and-set updates. The SQLite-specific
write-lock statement is isolated inside the reservation service. PostgreSQL can replace it with a
transaction-scoped advisory lock or locked budget-counter row without changing caller behavior,
fingerprinting, reservation states or AI claim semantics.

## Failure recovery strategy

- A definitive pre-request failure releases the reservation.
- An ambiguous failure after delivery starts is marked expired/uncertain and remains counted
  conservatively until reconciliation.
- Stale AI claims become retryable only within the configured attempt limit; exhausted contexts
  become permanent failures requiring manual review.
- Recovery is database-backed, idempotent and safe to run at startup or maintenance time.

## Test strategy

- Five concurrent callers for one lead/context: one ledger row and at most one adapter call.
- Twenty concurrent unit reservations against limit ten: at most ten reserved/finalized units.
- Late competing caller does not invoke the adapter.
- Expired claim takeover increments attempts without creating another row.
- Successful response cache causes zero additional adapter calls.
- Semantic fingerprint stability and reaction exclusion tests.
- Three failures stop before a fourth paid attempt.
- Global kill switch overrides all live flags and unlock values.
- Pytest outbound socket guard remains active.
- Alembic checks cover fresh DB, existing DB copy and repeated upgrade.
- CI runs Ruff, compileall, migrations and pytest without external secrets.
