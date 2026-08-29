# Meta activation boundary

Lead Radar currently has no connected Meta adapter. Internal audience membership is useful
for analysis but is never treated as an external Custom Audience, Lookalike or targeting ID.

`MetaAudienceBlueprint` describes the intended activation mode and its requirements.
`MetaTargetingRecipe` is a versioned local plan. `MetaInterest` can only be populated from
the future catalog adapter, while `MetaInterestMapping` can reference only an ID already
stored in that catalog. `MetaExportCandidate` separates per-contact first-party eligibility
from internal membership. `MetaAudienceSync` is reserved for idempotent external delivery;
no row is created while the connector is unavailable.

All synchronized blueprints and recipes therefore show `NOT_CONNECTED`, contain no external
audience IDs, no fictional interest IDs and no invented geo/age constraints. Confirmed
exports return HTTP 503 and cannot mutate a contact to `EXPORTED`. Privacy-safe dry-run
counts remain available for operator review.

Audience facets are transient query parameters. They refine an existing audience in the UI
and analytics without inserting another `AudienceSegment`. Supported dimensions include
product family, intent, role, stage, quantity band, city, competitor source, recency,
confidence, value, horizon, rattan layer/role, manager assignment and deal outcome.
