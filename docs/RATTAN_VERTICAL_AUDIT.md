# Artificial Rattan Vertical Audit

## CURRENT BEHAVIOR
- Rattan classification existed primarily as product labels (`RATTAN_SOFA`, `RATTAN_ARMCHAIR`, etc.) and a keyword heuristic in `_product()`.
- Vertical switching in UI was partially a query-parameter filter rather than a deeply separated entity vertical.
- Raw rattan materials (coils, profiles, price per kg, flat/round extrusion) were not clearly distinguished from ready-made furniture.
- Generic terms (e.g. "стол", "кресло") lacked strict context validation, risking false classification as rattan business.

## EXPECTED BEHAVIOR
- Two completely separate workspaces: Furniture (`FURNITURE`) vs Artificial Rattan (`ARTIFICIAL_RATTAN`).
- Explicit `vertical` field across `PublicSignal`, `Evidence`, `Lead`, `ContactIntelligence`, `BusinessEntity`, `AudienceSegment`, and `Competitor`.
- Distinct taxonomy:
  - RAW MATERIALS: `RAW_RATTAN`, `FLAT_RATTAN`, `ROUND_RATTAN`, `HALF_ROUND`, `TUBE`, `COIL`, `KG_PRICE`, `COLOR`, `WIDTH`, `PROFILE`.
  - READY FURNITURE: `RATTAN_CHAIR`, `RATTAN_ARMCHAIR`, `RATTAN_SOFA`, `RATTAN_TABLE`, `RATTAN_SET`, `RATTAN_OUTDOOR`.
  - ROLES: `RAW_RATTAN_RESELLER`, `WHOLESALER`, `IMPORTER`, `DISTRIBUTOR`, `MANUFACTURER`, `FURNITURE_RESELLER`, `WEAVER`, `CRAFT_MASTER`, `BUYER`, `UNKNOWN`.
- Disambiguation: "стол" -> normal furniture; "ротанговый стол" -> rattan furniture; "цена за кг" / "бухта" -> raw rattan material.
- If live discovery is off, UI displays "Источник поиска выключен" instead of mock companies.

## BUGS
1. Missing `vertical` column in core signal and lead database schemas.
2. Keyword overlap causing standard furniture inquiries on general posts to map to rattan categories.
3. Lack of raw extrusion profile classification (flat, half-round, round).

## DATA RISKS
- Cross-contamination between furniture leads and raw material inquiries in CRM views.

## COST RISKS
- Low.

## FALSE POSITIVE RISKS
- High: Normal furniture buyer classified as industrial raw rattan wholesaler.

## FALSE NEGATIVE RISKS
- Moderate: Industrial B2B inquiries using technical terms ("гранулы", "полиротанг в бухтах", "пруток") missed without dedicated vocabulary.

## PROPOSED FIX
1. Add `vertical` column to `public_signals`, `leads`, `evidence`, and `audience_segments`.
2. Build dedicated `RattanTaxonomyService` with separate sub-classifiers for raw materials vs finished goods vs business roles.
3. Provide distinct workspace navigation in UI (`[ 🪑 Мебель ]` vs `[ 🌾 Искусственный ротанг ]`).

## TESTS REQUIRED
- `test_rattan_raw_material_vs_furniture_disambiguation`
- `test_general_furniture_never_classified_as_rattan_without_context`
- `test_rattan_business_role_classification_accuracy`
- `test_workspace_vertical_isolation`
