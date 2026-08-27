# Audience Engine V3 Audit

## CURRENT BEHAVIOR
- `AudienceService` computes memberships using boolean filters and counter aggregations over raw signals.
- Decayed interest score formula existed in helper functions but was not systematically stored and applied during membership evaluation.
- Membership in segments lacked granular explainability (e.g. why a user was placed in `hot-7d` or `dining-sets`).
- No dedicated `InterestEvidence` table tracking individual topic observations with timestamps and half-life decay.

## EXPECTED BEHAVIOR
- Segment memberships must be 100% explainable with traceable bullet points referencing evidence IDs.
- `InterestEvidence` records store each topic observation with confidence and half-life decay parameters.
- Lookalike / similarity engine derives feature vectors from pre-purchase attributes of `WON` deals (`OutcomeDNA`), with zero data leakage.
- Non-commercial reactions (likes, praise) must never count toward interest strength or multi-competitor affinity.

## BUGS
1. `calculate_decayed_interest_score` was computed on the fly in certain view helpers rather than driving the core membership evaluation query.
2. Audience membership explanations were generic strings rather than evidence-linked structured arrays.
3. Multi-competitor overlap did not filter out non-commercial comments.

## DATA RISKS
- Stale memberships persisting indefinitely if decay threshold does not trigger automatic eviction.

## COST RISKS
- Low: Audience calculations are purely local database queries.

## FALSE POSITIVE RISKS
- High: Casual commenters asking generic non-commercial questions placed into high-intent targeting segments.

## FALSE NEGATIVE RISKS
- Moderate: Contacts with strong historical intent evicted too quickly if half-life decay is overly aggressive.

## PROPOSED FIX
1. Create `InterestEvidence` model (`contact_id`, `topic`, `signal_id`, `strength`, `confidence`, `observed_at`, `expires_at`).
2. Upgrade `AudienceMembership` with structured `reasons_json` containing evidence-backed justifications.
3. Implement `OutcomeDNA` extraction based exclusively on pre-won signals.

## TESTS REQUIRED
- `test_interest_evidence_decay_eviction`
- `test_audience_membership_has_evidence_explanations`
- `test_non_commercial_reactions_excluded_from_segments`
- `test_outcome_dna_pre_purchase_isolation`
