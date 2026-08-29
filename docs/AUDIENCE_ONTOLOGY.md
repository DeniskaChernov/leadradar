# Audience Intelligence V4 ontology

Lead Radar separates facts, intelligence and activation objects instead of calling every
filter a new audience.

1. `PublicSignal` and `Evidence` preserve the observed public fact.
2. `InterestEvidence` is the idempotent commercial interpretation linked to that fact.
3. `ContactInterestProfile` stores the current, decayed topic score.
4. `AudienceSegment` is the physical database table for the logical
   `AudienceDefinition`. Its rows may only be synchronized from the curated registry.
5. `AudienceMembership` is a reproducible relation between a contact and an active
   definition. It stores evidence IDs, structured reasons, confidence and expiry.
6. First-party export eligibility remains a separate property. Membership in an internal
   audience does not imply that the contact can be uploaded to Meta.

The registry has ten families: `INTENT`, `PRODUCT`, `BUYER_ROLE`, `MARKET_BEHAVIOR`,
`VALUE`, `LIFECYCLE`, `OUTCOME_DNA`, `RATTAN_MARKET`, `FIRST_PARTY` and `SIMILARITY`.
Definitions are `ACTIVE`, `DRAFT` or `RETIRED`. Draft definitions are visible in the
registry but are never evaluated and never receive memberships.

The first V4 stage intentionally leaves rattan seller/manufacturer/import roles and
Outcome DNA audiences in `DRAFT`: the current data model cannot prove those memberships
without additional role/outcome services. This prevents plausible-looking but invented
audiences.

Confidence measures reliability of the supporting Evidence and is not copied from lead
value. Intent, fit and value use current decayed profiles; a historical maximum score cannot
keep priority or a high-intent membership alive. Competitor comparison uses only currently effective
commercial evidence, so a reaction or expired source cannot create overlap.
