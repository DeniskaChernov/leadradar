# Master Phase A — Core Safety Report

## What was simplified

The Instagram wrapper previously had a separate money path: check the current total, call the
provider and record usage afterward. That duplicated budget logic and left a race between check
and call. It now uses the same durable two-phase reservation service as OpenAI.

## Durable cost trail

`CostEvent` is the immutable, attributable cost history. A finalized reservation creates at most
one event through both a unique reservation reference and an idempotency key. It records units,
known token usage, known USD cost, provider/operation and optional business attribution.

`ExternalUsage` remains the operational quota history. It was not deleted because current daily
limits and existing reports depend on it.

## Versioned pricing

`PricingConfig` stores provider/operation/model prices with an effective date. Updating a price
creates a new row and preserves the old row. No provider prices are seeded or invented: when a
price is unknown, `CostEvent.cost_usd` is `NULL`.

The existing System screen contains a compact pricing editor and active-price table. A separate
navigation tab was intentionally not added because pricing is a system setting, not a daily sales
workflow.

## Provider flow

1. Check the absolute live/kill switches.
2. Atomically reserve the daily budget in the database.
3. Persist `call_started_at`.
4. Invoke the adapter.
5. Finalize actual usage and create `ExternalUsage` plus `CostEvent` exactly once.
6. On an ambiguous post-start failure, finalize conservatively instead of releasing spend.

For paginated Instagram comments, the maximum permitted pages are reserved before the call. Any
unused reservation is reconciled to actual pages on success; a failure is counted conservatively.

## Maturity and limits

- Core ledgers and pricing configuration: `OFFLINE`.
- OpenAI and Instagram live calls: disabled during implementation.
- Provider prices: `NOT_CONFIGURED` until the owner enters verified rates.
- Token-level OpenAI actuals: supported by the ledger, but the current adapter does not yet expose
  response token usage; no values are fabricated.
- Unit-economics aggregation/dashboard remains a later phase.
- Controlled live pilot remains blocked.
