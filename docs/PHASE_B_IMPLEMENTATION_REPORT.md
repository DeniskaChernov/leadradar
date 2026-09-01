# Phase B Implementation Report

## Scope completed

Phase B hardens AI idempotency, atomic daily-budget reservation, usage history and
crash recovery. It does not enable live OpenAI/Instagram/Telegram traffic and does not
claim production readiness.

## Durable AI request contract

- Stable unique key: `(lead_id, analysis_version, context_fingerprint)`.
- Contract version: `3.0`; prompt and response-schema versions are persisted.
- Canonical fingerprinting is isolated in `AIContextFingerprintService` and includes only
  meaning-bearing context. Non-commercial reaction history is excluded.
- Claim leases are database-backed, configurable and owned by a host/PID/instance worker ID.
- Cached successes return without a provider call. Live leases block competitors. Expired
  leases can be taken over atomically.
- Pre-call failures do not consume a paid attempt. Three failed calls stop future automatic
  attempts with `PERMANENT_FAILURE`.

## Atomic budget and usage history

- SQLite uses `BEGIN IMMEDIATE` before budget read/check/write, so the limit is enforced
  across processes rather than only within one asyncio loop.
- Each reservation has a stable key, owner, reserve/start/expiry/release/finalize timestamps,
  estimates, actuals and structured details.
- Delivery start is persisted before the adapter call. A post-start network failure is billed
  conservatively instead of releasing capacity that may already have been consumed.
- Reservation finalization is compare-and-set. `ExternalUsage.idempotency_key` makes the
  resulting history exactly once even if finalization is repeated.

## Recovery and diagnostics

- Startup recovery releases expired reservations that never started delivery.
- Started expired reservations are finalized conservatively; if the matching AI ledger already
  contains a success, recovery records that known success instead of an unknown outcome.
- Stale AI claims become `RETRYABLE` or `PERMANENT_FAILURE` according to the attempt limit.
- `/system` exposes AI status counts, active reservations, stale AI leases and uncertain usage
  from the local database without external calls.

## Schema and configuration

- Migration: `c7f1a8d42e90_phase_b_ledger_contract_hardening.py`.
- New safe settings: `AI_REQUEST_LEASE_SECONDS=180`, `AI_REQUEST_MAX_ATTEMPTS=3`,
  `LEAD_ANALYSIS_VERSION=3.0`, `EXTERNAL_KILL_SWITCH=true`.
- Existing data is preserved and backfilled. No secret values are committed.

## Verification evidence

- Ruff: clean.
- Python compileall: clean.
- Pytest: 186 passed.
- Five concurrent callers for one AI context: one provider call maximum.
- Twenty concurrent reservations at limit ten: ten reservations maximum.
- Repeated finalize: one usage row.
- Three paid failures: fourth provider call blocked.
- Fresh migration, existing working database upgrade and repeated upgrade: passed.
- Working database backup created before migration.

## Honest remaining limits

- No live provider call was made, so provider-specific billing reconciliation and returned token
  counts remain unverified in production.
- The SQLite locking strategy is correct for this deployment mode but intentionally serializes
  writers. PostgreSQL should replace it with a locked counter row or advisory lock at scale.
- Production readiness remains blocked on later phases and a separately authorized controlled
  live pilot.
