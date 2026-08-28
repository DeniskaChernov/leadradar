# Lead Radar V4 notification delivery

## Delivery contract

The database is the delivery source of truth. A notification outbox row is committed before a
Telegram request starts. Its `idempotency_key` is stable per business event and destination:

- lead signal: `lead:<lead_id>:chat:<chat_id>`;
- significant change: `change:<change_id>:chat:<chat_id>`.

Both the business target constraint and the idempotency key are unique in the database. Multiple
workers may discover the same pending row, but only one atomic update can acquire its lease.

## State machine

```text
PENDING ──claim──> PROCESSING ──Telegram receipt saved──> SENT
   ^                   │
   │                   ├─ explicit Telegram rejection ──> FAILED ──due retry──┘
   │                   │
   │                   └─ ambiguous network outcome ──> UNCERTAIN
   │                                                       │
   └──────── manager confirms “not sent” ──────────────────┘
                                                           └─ confirms sent ─> SENT
```

Before calling Telegram, the worker persists `delivery_started_at`. An expired lease without that
marker is safe to requeue. An expired lease with the marker is never retried automatically because
the message may already have reached Telegram. It moves to `UNCERTAIN` for explicit reconciliation.

`TELEGRAM_NOTIFICATION_LEASE_SECONDS` controls lease duration (default 120 seconds). Every worker
has a unique owner ID and every claim has a random token; only the token owner can persist success
or failure.

## Signal First and enrichment

With `ALL_NEW_COMMENTS`, a non-baseline public signal is saved first, the initial manager message is
sent second, and analysis follows. The Telegram `chat_id` and `message_id` are persisted. Completed
analysis atomically claims one edit operation and updates the original message. If Telegram rejects
the edit, exactly one concise enrichment follow-up is attempted. A crash or ambiguous follow-up
outcome suppresses further automatic sends.

Baseline, replay and tests keep production delivery disabled. Telegram handlers do not call the
Instagram provider.

## Phase G read-only readiness preview

`NotificationReadinessService` evaluates recent persisted leads without creating outbox rows or
calling Telegram. It uses the same observable inputs as production delivery: global or competitor
policy, baseline flag, local analysis status, HOT threshold, assigned manager/admin target routing,
and existing `NotificationLog` state.

The `/system` panel distinguishes configuration from an active delivery worker. A configured bot
token is not presented as active delivery when the application runs with `--web-only`. Decisions
are shown as `ELIGIBLE`, `QUEUED`, `SENT`, `SUPPRESSED`, `BLOCKED`, `FAILED`, or `UNCERTAIN` and use
masked idempotency patterns (`lead:<id>:chat:*`) rather than exposing manager chat identifiers.

This preview is readiness evidence only. It does not replace a separately authorized controlled
Telegram delivery pilot.

## Recovery procedure

1. Inspect rows in `UNCERTAIN`; do not reset them directly to `PENDING`.
2. Verify the target chat and delivery time in Telegram.
3. Call `resolve_uncertain_lead_delivery` or `resolve_uncertain_change_delivery`:
   - `delivered=True` records `SENT` and the known Telegram message ID;
   - `delivered=False` records the decision and safely requeues the row.
4. Run the normal outbox flush. The resolution and timestamps remain auditable.

## Verified invariants

- two worker instances produce one delivery claim;
- an expired pre-send claim is safely recovered;
- an expired post-start claim becomes `UNCERTAIN` and is not resent;
- an ambiguous network failure is not retried automatically;
- message enrichment has one edit claimant and at most one fallback;
- migration works on the existing DB copy, a fresh DB, repeated upgrade and downgrade/re-upgrade.
