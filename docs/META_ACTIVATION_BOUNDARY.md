# Meta activation boundary

Lead Radar keeps Meta spend fail-closed until live unlock. Internal audience membership is useful
for analysis but is never treated as an external Custom Audience, Lookalike or targeting ID
while the connector is `NOT_CONNECTED`.

`MetaAudienceBlueprint` describes the intended activation mode and its requirements.
`MetaTargetingRecipe` is a versioned local plan. `MetaInterest` can only be populated from
the catalog adapter, while `MetaInterestMapping` can reference only an ID already
stored in that catalog. `MetaExportCandidate` separates per-contact first-party eligibility
from internal membership. `MetaAudienceSync` is reserved for idempotent external delivery
records tied to blueprints.

While Meta live is OFF, confirmed exports return HTTP 503 / `NOT_CONNECTED` and cannot
mutate a contact to `EXPORTED`. Privacy-safe dry-run counts remain available for operator review.

When Meta Ads live is explicitly unlocked (`META_ADS_*` + kill-switch unlock),
`MetaAdsService.create_custom_audience` creates a **PAUSED** Custom Audience and uploads
SHA-256 phone digests for `FIRST_PARTY_ELIGIBLE` contacts only. No Lookalike is created
automatically. Campaign drafts remain PAUSED.

Audience facets are transient query parameters. They refine an existing audience in the UI
and analytics without inserting another `AudienceSegment`. Supported dimensions include
product family, intent, role, stage, quantity band, city, competitor source, recency,
confidence, value, horizon, rattan layer/role, manager assignment and deal outcome.
