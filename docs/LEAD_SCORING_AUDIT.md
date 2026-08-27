# Lead Scoring V3 & Commercial Signals Audit

## CURRENT BEHAVIOR
- Scoring relied on monolithic score calculation (0–100) combining keyword weights with history boosts.
- Multi-competitor boosts were awarded based on raw comment counts across competitors, even if some comments were purely non-commercial reactions ("🔥", "класс").
- Intent sequence intelligence was primitive (equal weight to repeated identical intents vs progression from price to delivery).
- B2B quantity thresholds were hardcoded inconsistently across several service files.

## EXPECTED BEHAVIOR
- Decomposed Scoring Architecture:
  - `intent_score` (commercial intent depth: price, availability, delivery, order, bulk).
  - `activity_score` (validated signal recency and progression).
  - `specificity_score` (model/color/dimensions/quantity specifics).
  - `value_score` (order volume, basket size, B2B tier).
  - `fit_score` (alignment with core catalog offering).
  - `source_quality_score` (organic comment vs bot/giveaway noise).
  - `confidence_score` (clarity and linguistic confidence).
  - `priority_score` (weighted synthesis for queue ranking).
- Commercial Signal Quality Tiers:
  - `NON_COMMERCIAL` (emoji, reaction, praise, greetings).
  - `WEAK_COMMERCIAL` (generic inquiry, vague interest).
  - `MEDIUM_COMMERCIAL` (specific price, color, size, catalog request).
  - `STRONG_COMMERCIAL` (availability, delivery terms, order placement, wholesale/B2B quantity).
- Centralized `B2BPolicy`: Single configuration source defining thresholds (10+ items, commercial context, HoReCa markers).
- Sequence Intelligence: Boost progression (`PRICE` -> `AVAILABILITY` -> `DELIVERY`) while applying diminishing returns on repetitive inquiries.
- Half-life decay per signal type (PRICE: 14d, AVAILABILITY: 10d, DELIVERY: 14d, BUY: 21d, QUANTITY: 30d, CATALOG: 21d, FOLLOWER: 180d, BUSINESS_ROLE: 365d).

## BUGS
1. Non-commercial reactions inflated history count and triggered false HOT scores.
2. Repetitive identical comments produced linear score increases without saturation capping.
3. Inconsistent B2B thresholds across different modules.

## DATA RISKS
- Over-scoring old leads due to lack of real-time time decay during pipeline execution.

## COST RISKS
- Low.

## FALSE POSITIVE RISKS
- High: Casual social users asking trivial questions elevated to high-priority sales queues.

## FALSE NEGATIVE RISKS
- Low: Clear commercial intents are well captured.

## PROPOSED FIX
1. Implement `CommercialSignalQuality` classification.
2. Build `LeadScorerV3` producing decoupled component metrics and evidence links.
3. Create centralized `B2BPolicy` class.
4. Establish 150+ multilingual golden test fixtures.

## TESTS REQUIRED
- `test_non_commercial_reactions_produce_zero_lead_score`
- `test_sequence_intelligence_progression_vs_repetition`
- `test_b2b_policy_centralized_thresholds`
- `test_multilingual_golden_scenarios_accuracy`
