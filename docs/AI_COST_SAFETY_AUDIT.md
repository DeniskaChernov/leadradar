# AI Cost & Safety Audit

## CURRENT BEHAVIOR
- External API calls are guarded by `ExternalUsageService`, a durable reservation ledger and
  finalized `external_usage` rows.
- SQLite reserves budget under `BEGIN IMMEDIATE`, so independent processes cannot pass the same
  check-and-reserve window concurrently.
- Expired reservations are marked `EXPIRED` and reclaimed; finalize/release are compare-and-set
  transitions and cannot double-count one reservation.
- OpenAI analysis uses a canonical context fingerprint plus a durable `AIRequest` claim token.
  Competing workers cannot issue the same lead/context request simultaneously.
- `EXTERNAL_KILL_SWITCH=true` overrides both Instagram and OpenAI live enablement.

## EXPECTED BEHAVIOR
- Atomic Two-Phase Budget Reservation (`ExternalBudgetReservation` table):
  1. Reserve units in DB transaction. If reserved + used >= limit, reject request immediately.
  2. Perform API call.
  3. Finalize actual usage or release reservation on error.
- Canonical Context Fingerprint (SHA-256):
  Combines analysis contract version, model family, comment text, post caption, contact identity, validated previous commercial signals, CRM facts, evidence IDs, vertical, and catalog context.
- Global Kill Switch (`EXTERNAL_KILL_SWITCH=true`) overriding all external services instantly.

## REMAINING GAP

The backend exposes deterministic `CostPreview` calculations, but the UI still needs a confirmation
modal before every future bulk follower/backfill operation. Those operations remain disabled.

## DATA RISKS
- Potential discrepancy between recorded `external_usage` and real provider billing if network drops during response write.

## COST RISKS
- High: Uncontrolled concurrency could exhaust budget on retried scans or bulk replays.

## FALSE POSITIVE RISKS
- N/A (Cost safety layer).

## FALSE NEGATIVE RISKS
- False budget exhaustion if expired/abandoned reservations are not automatically reclaimed or released.

## IMPLEMENTED FIX

Migration `e8a4c2f91b70` creates both ledgers, their unique constraints and indexes. AI requests
require a real persisted `lead_id`; the previous unsafe fallback to ID 1 was removed. A random claim
token protects result persistence and expired claims may be recovered without allowing two active
workers.

## TESTS REQUIRED
- `test_budget_reservation_atomic_race`
- `test_budget_reservation_expiry_reclaim`
- `test_kill_switch_blocks_all_outbound_calls`
- `test_duplicate_concurrent_ai_requests_share_single_call`
