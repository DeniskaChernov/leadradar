# Artificial Rattan Vertical Audit

## CURRENT BEHAVIOR (Phase E verified)
- Rattan is a persisted vertical on PublicSignal, Evidence, Lead, AudienceSegment and Competitor.
- `RattanTaxonomyService` requires explicit rattan context before assigning the vertical.
- Raw materials, finished furniture and observable market roles are classified separately.
- `/rattan` is a separate DB-backed workspace; it does not inject demo companies.
- The offline rebuild is idempotent and propagates taxonomy through existing evidence.

## EXPECTED BEHAVIOR
- Two completely separate workspaces: Furniture (`FURNITURE`) vs Artificial Rattan (`ARTIFICIAL_RATTAN`).
- Explicit `vertical` field across `PublicSignal`, `Evidence`, `Lead`, `ContactIntelligence`, `BusinessEntity`, `AudienceSegment`, and `Competitor`.
- Distinct taxonomy:
  - RAW MATERIALS: `RAW_RATTAN`, `FLAT_RATTAN`, `ROUND_RATTAN`, `HALF_ROUND`, `TUBE`, `COIL`, `KG_PRICE`, `COLOR`, `WIDTH`, `PROFILE`.
  - READY FURNITURE: `RATTAN_CHAIR`, `RATTAN_ARMCHAIR`, `RATTAN_SOFA`, `RATTAN_TABLE`, `RATTAN_SET`, `RATTAN_OUTDOOR`.
  - ROLES: `RAW_RATTAN_RESELLER`, `WHOLESALER`, `IMPORTER`, `DISTRIBUTOR`, `MANUFACTURER`, `FURNITURE_RESELLER`, `WEAVER`, `CRAFT_MASTER`, `BUYER`, `UNKNOWN`.
- Disambiguation: "стол" -> normal furniture; "ротанговый стол" -> rattan furniture; "цена за кг" / "бухта" -> raw rattan material.
- If live discovery is off, UI displays "Источник поиска выключен" instead of mock companies.

## FIXED IN PHASE E
1. Migration `a6d4e2c91f30` adds the missing vertical columns and indexes.
2. Generic furniture without explicit rattan context stays in `FURNITURE`.
3. Raw extrusion profiles and price/unit markers have dedicated taxonomy values.
4. Furniture and rattan audience definitions are isolated by structured vertical criteria.
5. Integrity checks detect Lead/PublicSignal and Evidence/PublicSignal vertical drift.
6. Generic rattan context without material, product or market-role evidence stays at layer
   `NONE` instead of fabricating `RAW_MATERIAL` interest.
7. Explicit natural-rattan phrases are excluded from the artificial-rattan vertical.

## DATA RISKS
- Cross-contamination between furniture leads and raw material inquiries in CRM views.

## COST RISKS
- Low.

## FALSE POSITIVE RISKS
- Reduced but not eliminated: account names containing `rattan/rotang` can establish the
  vertical, but can no longer establish a raw-material layer on their own.

## FALSE NEGATIVE RISKS
- Moderate: Industrial B2B inquiries using technical terms ("гранулы", "полиротанг в бухтах", "пруток") missed without dedicated vocabulary.

## REMAINING GATES
1. Expand the current 24-case golden set to the pilot-size evaluation corpus.
2. Run the offline 500–1000 signal replay and measure precision/recall by layer and role.
3. Only after those gates, authorize a controlled live provider pilot and notification delivery.

## VERIFIED EVIDENCE
- 30 RU/UZ/EN golden and negative cases.
- Idempotent rebuild and workspace isolation integration tests.
- Empty-database and existing-database Alembic upgrade checks.
- 600-case deterministic robustness replay: 100% internal rattan precision, recall and
  layer accuracy, with zero duplicate ingestion rows.
- Full offline suite: 194 passed; Ruff and compileall clean.
- Working database integrity: zero duplicate keys and zero vertical mismatches.
