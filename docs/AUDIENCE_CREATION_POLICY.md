# Audience creation and anti-fragmentation policy

The only allowed source of persisted audience definitions is
`app/services/audience_registry.py`. Runtime code and UI filters must not insert arbitrary
definitions. A new definition requires a reviewed code change, business meaning, evidence
rule, lifecycle policy, tests and a migration-compatible registry sync.

The following are facets, not audiences: city, district, age, gender, language, exact date,
exact score, exact quantity, manager, competitor, Reel, post, SKU, individual product,
colour and dimensions. They may be composed in views, analytics or a future campaign
blueprint without generating another database definition.

Before promoting a `DRAFT` definition to `ACTIVE`, prove all of the following:

- it represents a stable commercial cohort rather than a reporting slice;
- its membership is reproducible from persisted Evidence;
- absence of evidence never becomes positive evidence;
- confidence and current score have explicit minimums;
- decay and recency behaviour are tested;
- internal membership and export eligibility remain separate;
- it is not equivalent to an existing audience plus one or more facets.

Meta connectivity is currently `NOT_CONNECTED`. Registry `meta_use_case` is descriptive
planning metadata only and never claims that a Meta audience exists.
