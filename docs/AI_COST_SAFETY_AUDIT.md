# AI Cost & Safety Audit

## CURRENT BEHAVIOR
- External API calls (OpenAI, ScrapeCreators, BrightData) are guarded by `ExternalUsageService` recording rows in `external_usage`.
- Daily limits are checked prior to calls via `get_daily_usage(service) < limit`.
- In-flight concurrent requests do not hold an atomic reservation, meaning 10 parallel tasks can all pass the daily check at usage=9 (limit=10) and issue 10 external requests.
- Caching in `AnalysisCache` keys only by string text or crude hash, without factoring all contextual parameters (version, vertical, previous commercial signals, CRM facts).

## EXPECTED BEHAVIOR
- Atomic Two-Phase Budget Reservation (`ExternalBudgetReservation` table):
  1. Reserve units in DB transaction. If reserved + used >= limit, reject request immediately.
  2. Perform API call.
  3. Finalize actual usage or release reservation on error.
- Canonical Context Fingerprint (SHA-256):
  Combines analysis contract version, model family, comment text, post caption, contact identity, validated previous commercial signals, CRM facts, evidence IDs, vertical, and catalog context.
- Global Kill Switch (`EXTERNAL_KILL_SWITCH=true`) overriding all external services instantly.

## BUGS
1. Non-atomic check-then-act pattern in `usage_service.py` allows race condition over-spending.
2. Concurrent cache miss can result in duplicate OpenAI calls for the exact same lead and context.
3. No pre-flight cost estimation preview modal for bulk backfill / scan operations.

## DATA RISKS
- Potential discrepancy between recorded `external_usage` and real provider billing if network drops during response write.

## COST RISKS
- High: Uncontrolled concurrency could exhaust budget on retried scans or bulk replays.

## FALSE POSITIVE RISKS
- N/A (Cost safety layer).

## FALSE NEGATIVE RISKS
- False budget exhaustion if expired/abandoned reservations are not automatically reclaimed or released.

## PROPOSED FIX
1. Create `ExternalBudgetReservation` model with status (`RESERVED`, `FINALIZED`, `RELEASED`, `EXPIRED`) and expiration timestamp.
2. Build `AIRequest` ledger ensuring one analysis per context fingerprint.
3. Add `EXTERNAL_KILL_SWITCH` environment variable and UI button.
4. Implement `CostPreview` calculation for all bulk operations.

## TESTS REQUIRED
- `test_budget_reservation_atomic_race`
- `test_budget_reservation_expiry_reclaim`
- `test_kill_switch_blocks_all_outbound_calls`
- `test_duplicate_concurrent_ai_requests_share_single_call`
