# Product Catalog and grounded Next Best Action

## Source of truth

The products table is the only internal source for product claims made by the grounded
recommendation engine. The initial seed contains exactly the ten positions confirmed in the
current master specification:

CORDA, VERTEX, two TAPER ROTANG dimensions, TODO, ROERO, NOERO, JARDIN, LIRA and COMO.

The seed does not invent SKU, stock, COGS, colors or product category. Those fields remain null,
empty or UNCONFIRMED until a manager explicitly verifies them.

## Safe synchronization

Startup calls ProductCatalogService.sync_confirmed_catalog(). The operation is idempotent and
keys products by an internal canonical key. Existing rows and manager-confirmed fields are never
overwritten by later startup synchronization.

## Manager verification

The /catalog page shows confirmed facts and explicit unknown states. A manager can verify:

- category;
- current stock;
- COGS.

Blank stock or COGS is stored as unknown, not zero. Category matching becomes eligible for product
recommendations only after it is confirmed.

## Grounded recommendations

NextBestActionEngine receives persisted matching Product records. It may state only fields present
on those records. When stock is unknown, the recommendation explicitly asks the manager to check
availability. It never invents:

- SKU;
- discount;
- delivery time;
- stock;
- wholesale price;
- designer files or commissions.

When no catalog match exists, the safe action is to clarify model, quantity, dimensions and color
and check availability before making an offer.

## Removed prototype behavior

The old hardcoded agent returned fake score 91, fake evidence, fake catalog SKU, stock, 10% discount
and 24-hour delivery. It has been removed. The /api/agent/query endpoint now returns
503 NOT_CONNECTED. The internal MCP definitions remain as a future contract, but execution returns
NOT_CONNECTED until individual tools are wired to real services.
