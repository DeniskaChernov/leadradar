# Unit Economics & Cost Ledger Audit

## Current verified behavior

- `UnitEconomicsEngine` reads immutable `CostEvent` rows and persisted signals, leads and
  WON deals. It no longer accepts invented aggregate spend/count inputs.
- Periods are explicit rolling windows: 24 hours, 7 days and 30 days.
- Cost per signal, commercial signal, lead, HOT, B2B and WON is returned only when every
  cost event in the selected scope has a known price.
- Provider, vertical and competitor-source breakdowns are derived from direct foreign keys,
  attributed leads or the public `source_account` saved by the provider wrapper.
- `/analytics` shows known spend, tariff coverage, provider/vertical breakdowns and source
  economics without calling an external provider.

## Safety decisions

1. An unpriced `CostEvent` makes cost-per metrics unknown (`None`), not `$0` and not a
   deceptively precise partial value.
2. No cost events means “no cost evidence”, not “free acquisition”.
3. Deal revenue is stored in UZS while acquisition costs are stored in USD. ROI stays
   unavailable until an explicit, versioned FX policy exists.
4. Gross profit stays unavailable because the current deal/catalog model does not persist
   verified COGS for the sold line item.
5. Manual server cost, Google, Meta or any other provider appears only after an actual
   `CostEvent`; placeholder spend is never generated.

## Attribution limitations

- Period metrics compare activity occurring inside the same rolling window. They are not yet
  cohort CAC for leads acquired earlier and won later.
- Historical Instagram events recorded before `source_account` attribution remain in the
  “Без атрибуции” bucket.
- Audience and campaign foreign keys are already available in the ledger, but their UI slices
  will remain empty until real attributed events exist.
- Currency conversion and COGS require explicit domain models before ROI/gross margin can be
  enabled.

## Verified tests

- DB-backed CPL/CPH/CPB2B/CPW from persisted cost and outcome rows.
- Unpriced operations block derived cost metrics.
- Source attribution works through lead and normalized source account.
- Empty ledger never claims zero acquisition cost.
- Analytics page renders the honest unavailable states.
- Full offline repository gate: 197 tests passed; Ruff and compileall clean.

## Maturity

`OFFLINE`. No provider or paid live test was executed. Production ROI and live billing
reconciliation remain blocked.
