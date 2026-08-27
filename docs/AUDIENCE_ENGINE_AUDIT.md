# Audience Engine V3 Audit

## CURRENT BEHAVIOR

- Phase D core is implemented offline. Every validated commercial Lead is projected into
  idempotent `InterestEvidence` rows linked to a real `Evidence` and `PublicSignal` row.
- `ContactInterestProfile` stores a decayed score per vertical, dimension and topic. It includes
  confidence, first/last observation, commercial-signal count, source count and Evidence IDs.
- Audience membership is unique by segment/contact and stores structured `reasons_json`, real
  `evidence_ids_json`, expiry and `engine_version=3.0`.
- `OutcomeDNA` snapshots only evidence whose `observed_at` is not later than the deal's `won_at`.
- Reactions and other V3 non-commercial signals do not create InterestEvidence and do not count
  as competitor overlap.

## EXPECTED BEHAVIOR

- Memberships must remain fully reproducible from persisted evidence after restart.
- Expired commercial interest must leave the active segment without deleting history.
- Similarity must use non-sensitive commercial features and return a human-readable explanation.
- Outcome learning must use only facts observed before WON and must never use WON as a feature.

## BUGS FIXED

1. Generic membership strings were replaced with structured, Evidence-linked reasons.
2. The half-life formula now drives persisted interest-profile scores and membership expiry.
3. Reaction/noise rows no longer inflate activity or multi-competitor source counts.
4. Recalculation no longer creates duplicate observations, profiles, memberships or OutcomeDNA.
5. Product and intent confidence is no longer calculated from raw occurrence counters alone.

## DATA RISKS

- Legacy analyses are accepted as commercial only when their saved status and score pass the
  compatibility gate. They should be re-analysed offline before a live pilot.
- Existing data contains mostly one-source price signals, so current audience distribution is not
  representative of production demand.
- Product taxonomy still belongs to the legacy furniture/rattan boundary and will be rebuilt in
  Phase E.

## COST RISKS

- Audience V3 is database-only and makes no network or paid AI calls.
- Full recalculation is currently sequential by contact; safe but not yet optimized for a large DB.

## FALSE POSITIVE RISKS

- Legacy custom analyzer results do not contain all V3 component scores; compatibility falls back
  to the saved lead score.
- Current active threshold (20/100) needs calibration on a larger golden/replay dataset.

## FALSE NEGATIVE RISKS

- A signal without a persisted Evidence row is intentionally excluded even when Lead data exists.
- Aggressive half-life values may evict legitimate long-cycle demand and require vertical-specific
  calibration.

## IMPLEMENTED FIX

1. Migration `f3b9d7a61c20` adds `interest_evidence`, `contact_interest_profiles`, `outcome_dna`
   and structured membership explanation fields.
2. Recalculation performs deterministic upserts and preserves expired observations as inactive
   history.
3. Profiles combine decayed observations with diminishing returns and confidence weighting.
4. UI shows why each contact belongs to a segment and the supporting Evidence IDs.
5. Data-integrity checks cover all new unique scopes.

## TESTS

- Interest evidence/profile/membership recalculation is idempotent.
- Membership explanations reference real Evidence IDs.
- A reaction at another competitor creates no interest and no multi-source membership.
- Decayed PRICE interest expires while its historical observation remains stored.
- OutcomeDNA excludes signals observed after WON.
- Full offline suite: 171 passed, zero paid/network calls.

## REMAINING

- Add 100+ audience golden scenarios and measure segment precision/recall.
- Add similarity explanations and aggregate won-customer pattern reporting.
- Run the 500–1000 signal offline replay and publish audience accuracy in the pilot report.
- Validate decay thresholds on real, consented pilot outcomes before production use.
