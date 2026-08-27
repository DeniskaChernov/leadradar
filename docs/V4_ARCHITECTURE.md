# Lead Radar V4 architecture

## Phase 1 foundation

V4 keeps the existing FastAPI/Jinja, Telegram, CRM and Instagram pipeline. The data foundation
is additive: legacy `Comment`, `Competitor`, `Contact`, `Lead` and their IDs remain valid.

```text
Contact ----------------------┐
                              ├─ PublicSignal ─ Evidence
BusinessEntity ─ BusinessAlias┘        │
       │                               └─ legacy Comment (during compatibility period)
       └─ legacy Competitor
```

## Identity boundaries

- `Contact` is a person/public person account.
- `BusinessEntity` is a company, shop, manufacturer, restaurant or supplier.
- A mutable username is not a stable person identifier. Platform user ID wins; username
  reassignment creates a distinct contact and an immutable identity-change event.
- A business can have multiple aliases and multiple verticals.
- Weak name similarity never auto-merges businesses.
- Auto-resolution uses only verified stable public aliases: domain, Google Place ID, public
  phone or marketplace seller ID. Conflicting strong identifiers stop for review.

## Universal signal identity

Every signal has:

- `(platform, signal_type, external_id)` when the source provides a stable ID;
- a mandatory `dedupe_key` as the canonical idempotency key;
- subject (`CONTACT`, `BUSINESS`, `UNKNOWN`) and optional contact/business links;
- vertical, source, timestamps, quality/confidence and baseline state;
- raw public payload only when the provider supplies it.

Existing Instagram comments use `instagram:COMMENT:<platform_comment_id>`. The database has
both a unique external identity and a unique dedupe key. A duplicate therefore cannot pass even
if two workers reach the insert concurrently.

## Evidence boundary

`Evidence` is the source of observable facts. Each evidence row has a stable `evidence_key`, a
source signal, observation time, text/source URL and bounded strength/confidence. AI may interpret
evidence later, but it must not invent evidence IDs. Business aliases may reference evidence.

## Compatibility and dual-write

For every new Instagram comment, `ContactService` commits in one transaction:

1. legacy Competitor/Post/Contact/Comment;
2. BusinessEntity and Instagram handle alias if missing;
3. universal PublicSignal;
4. source Evidence;
5. immutable `COMMENT_FOUND` event.

All downstream lead, audience and Telegram code continues to use existing IDs. Phase 1 adds no
external API call and does not enable scheduled monitoring or OpenAI.

## Migration and rollback

Revision `4b1f6a9c2d70`:

- creates business/evidence tables and indexes;
- extends `public_signals` and `market_candidates`;
- backfills one business/alias per legacy competitor;
- backfills one universal identity/evidence row per legacy signal;
- preserves old rows and foreign keys.

Verified paths: fresh upgrade, current-database-copy upgrade, repeated upgrade,
downgrade to `c93a1f7d2e40`, re-upgrade and Alembic schema check. The working SQLite database is
backed up before applying the revision.

## Next phase boundary

Phase 2 is complete. Notification delivery now uses durable database leases, stable idempotency
keys, stale-claim recovery and an explicit `UNCERTAIN` state for ambiguous Telegram outcomes. The
full contract and recovery procedure are documented in `V4_NOTIFICATION_PIPELINE.md`.

Phase 3 may add versioned intelligence factors, confidence and evidence-linked scoring. It must
remain rule-first by default, preserve database-first Signal First ordering, and make no live API
calls in tests.
