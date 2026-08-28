# Lead Scoring V3 & Commercial Signals Audit

## CURRENT BEHAVIOR

- The production rule pipeline now returns Intelligence `3.0`, not the disconnected V6 demo calculator.
- `LeadScorerV3` decomposes priority into intent, activity, specificity, value, fit, source quality and confidence.
- History uses only locally validated commercial intents. Praise, emoji and unrelated comments are excluded from repetition and multi-competitor counts.
- Activity applies intent-specific half-life decay and diminishing returns. Known progressions such as PRICE → AVAILABILITY → DELIVERY score above repeated PRICE.
- `B2BPolicy 1.0` is the shared quantity/context policy. Ten or twenty chairs alone are not B2B; commercial context, 30+ probable quantity or 50+ strong quantity is required.
- Rule and OpenAI output use real Evidence IDs only. Unknown IDs returned by a model are removed; absence of evidence reduces confidence.
- Buyer role and primary intent are independent axes. A restaurant owner asking about price remains `PRICE + B2B_HORECA`; a designer asking for a catalog remains `CATALOG + DESIGNER_CONTRACTOR`.
- Price objections remain visible as risk evidence, reduce priority deterministically and replace generic sales advice with a budget clarification that never invents a discount.

## EXPECTED BEHAVIOR

Evidence → features → component scores → confidence → priority, with every history contribution commercially validated, decayed and explainable. B2B thresholds must have one versioned owner.

## BUGS FIXED

1. Raw comment count and raw competitor count previously inflated activity.
2. Reactions previously contributed to `_history_boost`.
3. Twenty repeated PRICE questions grew almost linearly.
4. A quantity of ten automatically became B2B without business context.
5. Decay existed as an isolated helper but did not affect the lead/audience calculation.
6. The OpenAI prompt and cache contract still described Intelligence V2.
7. Early B2B/designer branches overwrote specific PRICE, DELIVERY, CATALOG and AVAILABILITY intents with generic BUY.
8. Objection penalties were exposed in the factor payload but did not affect the final priority.

## DATA RISKS

- Existing stored V2 scores are historical and are not silently rewritten. A controlled offline re-score/backfill is still required before comparing old and new score distributions.
- The original compatibility set still has 30 curated roots. A separate 200-phrase semantic
  benchmark now covers RU, UZ Latin and UZ Cyrillic without case/punctuation multiplication.

## COST RISKS

No external calls are introduced. The canonical AI fingerprint now excludes non-commercial history and includes stable contact identity, vertical and catalog context version.

## FALSE POSITIVE RISKS

Reduced: reactions cannot create cross-competitor activity and small household quantities cannot create a B2B role. Remaining risk is ambiguous short language routed to AI when live AI is enabled.

## FALSE NEGATIVE RISKS

Some valid B2B orders below 30 units need explicit business/HoReCa evidence. This is intentional for precision and must be evaluated against larger RU/UZ fixtures.

## PROPOSED NEXT FIX

Create a separately labelled unseen offline corpus and measure confusion by language, intent and buyer role. The current 200-scenario benchmark remains a calibration suite, not a production-accuracy claim.

## TESTS REQUIRED / STATUS

- reaction history exclusion — implemented;
- sequence progression vs repetition — implemented;
- half-life used in history scoring — implemented;
- repetition diminishing/cap — implemented;
- centralized contextual B2B thresholds — implemented;
- missing evidence lowers confidence — implemented;
- 200 multilingual semantic scenarios — implemented; internal calibration gate passes.
- role/intent contrast cases and objection-priority consistency — implemented.
- unseen production-like sample — not yet complete.
