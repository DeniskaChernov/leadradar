# Discovery Center — offline import and Diff Engine

## What is implemented

`/discovery` is the single review queue for companies that are not yet monitored. It reuses
`MarketCandidate`; it does not create a parallel market catalog.

The current stage is deliberately offline:

- CSV and XLSX files are parsed locally;
- no provider, search engine, Telegram or OpenAI request is made;
- an imported candidate is never activated automatically;
- promotion requires a confirmed public Instagram handle and creates a paused competitor.

## Import contract

Limits: 5 MB and 2,000 rows per file. The first row must contain headers. Common English and
Russian aliases are accepted:

| Meaning | Accepted examples |
|---|---|
| Company | `company`, `name`, `компания`, `название` |
| Instagram | `instagram`, `instagram_handle`, `username` |
| Website | `website`, `site`, `сайт` |
| Source | `source`, `источник`, `source_url`, `url` |
| Context | `city`, `location`, `category`, `description`, `notes` |
| Vertical | `vertical`, `вертикаль` (`FURNITURE` or `ARTIFICIAL_RATTAN`) |
| Diff fields | `price`, `цена`, `stock`, `наличие`, `role` |

At minimum, a company name is required. Instagram or website is strongly recommended.
Only public `http` and `https` links are retained.

## Idempotency and identity

Identity is resolved in this order:

1. normalized Instagram handle;
2. normalized website hostname;
3. Unicode-normalized company name.

The canonical key has a database unique index. The web service serializes local imports as an
additional guard. Re-importing an identical row updates `last_seen_at`, but creates neither a new
candidate nor a new diff.

## Diff Engine

Every changed snapshot receives a SHA-256 fingerprint. The immutable diff record stores the before
and after snapshots, changed fields, type and review timestamp. Supported current types:

- `NEW`;
- `UPDATED`;
- `PRICE_CHANGED`;
- `STOCK_CHANGED`;
- `ROLE_CHANGED`.

Only unreviewed changes appear in the UI. This prepares future paid enrichment to analyze new or
changed records instead of rescanning the whole catalog.

## Deliberately not implemented yet

- automatic Google Places, 2GIS, OSM, marketplace or web-search jobs;
- multilingual AI query expansion;
- schedules and paid cost preview;
- disappearance detection, which needs a complete source run boundary;
- automatic expensive analysis of imported changes.

Those operations remain blocked until their provider, budget reservation and explicit user
confirmation contracts are implemented.
