# Unit Economics & Cost Ledger Audit

## CURRENT BEHAVIOR
- `UnitEconomicsService` operated as an in-memory calculator estimating metrics from aggregate counts and fixed cost assumptions.
- There was no granular `CostEvent` ledger logging every paid token or API unit spend against specific leads, competitors, or campaigns.
- Provider pricing was hardcoded in python constants rather than configurable and versioned.
- Attribution of CAC and ROI by competitor source was approximated rather than tracked.

## EXPECTED BEHAVIOR
- `CostEvent` Ledger Model:
  - Records every individual cost transaction with `service`, `provider`, `operation`, `source`, `competitor`, `vertical`, `lead_id`, `audience_id`, `units`, `input_tokens`, `output_tokens`, `cost_usd`.
- Versioned `PricingConfig`:
  - Stores effective price schedules per provider/model with manual admin override support.
- Real Attribution Metrics:
  - Exact calculation of CPL (Cost per Lead), CPH (Cost per HOT), CPW (Cost per Won deal), CAC, and ROI attribution by competitor source, provider, and vertical.
  - Gross margin calculated only when actual product COGS is provided (never invented).
- Expenses Dashboard (`/system#expenses`):
  - Real-time spend tracking across daily/weekly/monthly intervals with remaining budget indicators and burn forecasts.

## BUGS
1. Hardcoded pricing in calculators prevented tracking price changes or multi-model cost differences.
2. Lack of persistent `CostEvent` table meant historical cost attribution could not be reconstructed after changes to rate constants.

## DATA RISKS
- Inaccurate ROI metrics if won deal revenue is not matched against full historical acquisition spend.

## COST RISKS
- Moderate: Lack of fine-grained cost attribution hides expensive, low-yield competitor monitoring targets.

## FALSE POSITIVE RISKS
- N/A.

## FALSE NEGATIVE RISKS
- N/A.

## PROPOSED FIX
1. Create `CostEvent` model and database table.
2. Build `PricingConfigService` supporting versioned provider rate cards.
3. Update `UnitEconomicsService` to aggregate directly from `CostEvent` records.
4. Implement interactive Expenses dashboard on `/system`.

## TESTS REQUIRED
- `test_cost_event_recorded_on_paid_call`
- `test_unit_economics_cpl_cph_cpw_calculation`
- `test_pricing_config_versioning_and_overrides`
- `test_attribution_by_competitor_and_vertical`
