# Core Architecture & Pipeline Audit

## CURRENT BEHAVIOR
- Ingestion of comments from Instagram provider creates records in `comments`, `public_signals`, and `leads`.
- De-duplication relies on `(competitor_id, platform_comment_id)` and `dedupe_key`.
- In-memory processing passes signals directly to the rule-based / hybrid analyzer.
- Pipeline execution can have edge cases where concurrent workers or retries might attempt duplicate creation if constraints are not fully enforced across all related entities.

## EXPECTED BEHAVIOR
- Strict invariant adherence (Rules 1–12).
- One Instagram comment ID generates exactly one `PublicSignal` and at most one `Lead`.
- Zero data loss on downstream worker failures (AI, Telegram, Audience).
- Deterministic idempotency keys for all stage transitions.

## BUGS
1. `_claim_message_edit` in Telegram notification service had a concurrency race with multiple workers claiming the same edit lease simultaneously.
2. Concurrent analysis of the same lead by multiple workers was not guarded by an atomic DB ledger table with expiration leases.
3. Outbox notifications did not have a unified transaction boundary with lead status updates in all handler paths.

## DATA RISKS
- Risk of orphaned records if comment ingestion commits before public signal creation fails.
- Risk of inconsistent state if lead workflow updates without recording a corresponding immutable `contact_events` row.

## COST RISKS
- Unrestricted AI calls if duplicate signals or retried jobs bypass cache without a canonical context fingerprint.

## FALSE POSITIVE RISKS
- Non-commercial reactions ("класс", "🔥", "муборак") could be counted toward contact history metrics if not strictly filtered as `NON_COMMERCIAL`.

## FALSE NEGATIVE RISKS
- Transliterated Uzbek requests ("nech pul", "qancha", "yetkazish bormi") might be missed if string normalization and keyword taxonomy are insufficient.

## PROPOSED FIX
1. Implement `AIRequest` ledger table with unique constraint `(lead_id, analysis_version, context_fingerprint)` and lease ownership.
2. Introduce `ExternalBudgetReservation` for two-phase atomic budget reservation.
3. Centralize transaction management in repository layer to guarantee all state changes generate `contact_events`.

## TESTS REQUIRED
- `test_signal_idempotency_duplicate_comments`
- `test_lead_idempotency_from_signal`
- `test_concurrent_worker_claim_collision`
- `test_crash_recovery_without_duplicate_processing`
