# Lead Radar V6 — Pre-Implementation Audit Report

## 1. Actual Architecture Summary

Lead Radar is a Python 3.12 application designed for commercial lead detection, market intelligence, and CRM workflow management across two primary business verticals: **Furniture** and **Artificial Rattan**.

### Component Map
- **Web App**: FastAPI app (`app/web/app.py`), Jinja2 SSR templates (`app/web/templates`), static assets (`app/web/static/app.css`).
- **Telegram Bot**: Aiogram 3 bot (`app/bot/handlers.py`, `app/main.py`), supporting command handlers, inline keyboards, and WebApp auth validation.
- **Data & Models**: SQLAlchemy 2 async models (`app/db/models/entities.py`), Alembic migrations (`alembic/versions/`), SQLite database (`lead_radar.db`) with `aiosqlite`.
- **Services**:
  - `ContactService`: Signal persistence, deduplication, contact upsert.
  - `LeadService`: Lead classification, scoring, change detection.
  - `AudienceEngine`: Segment evaluation, similarity scoring, export eligibility.
  - `ExportRecipeService`: Meta taxonomy mapping, 4 export recipes, SHA-256 privacy dry-runs.
  - `PlaceOpeningService`: Venue opening detection (`OpeningSignal`), review queue.
  - `TelegramLeadNotifier`: Outbox delivery, lease management, atomic claims.
  - `MarketIntelligenceService`: Competitor catalog sync, competitor stats.
  - `WebQueryService`: Aggregated queries, demand gap, 30-day heatmap.

## 2. Actual DB Schema & Migration Head

- **Current Alembic Migration Head**: `b1c2d3e4f5a6` (`opening_signals`).
- **Key Tables**:
  - `contacts`, `contact_intelligence`, `audience_segments`, `audience_memberships`
  - `competitors`, `posts`, `comments`, `public_signals`, `evidence`
  - `business_entities`, `business_aliases`, `opening_signals`
  - `leads`, `deals`, `contact_events`, `contact_tasks`, `notification_logs`, `external_usage`

## 3. Implemented V4/V5 Features

- ✅ Universal `PublicSignal`, `Evidence`, `BusinessEntity/Alias` models.
- ✅ Durable notification outbox with worker lease lock and atomic claim (`notification_logs`).
- ✅ Multi-factor lead scoring (`intent_strength`, `specificity_score`, `role_score`, `history_boost`), buyer roles (`B2B_HORECA`, `DESIGNER_CONTRACTOR`, `B2C_CONSUMER`).
- ✅ Golden calibration fixtures (`fixtures/golden_lead_calibration.json`, `fixtures/rattan_calibration.json`).
- ✅ Profile DNA, Jaccard-weighted contact similarity scoring, `ExportEligibility.FIRST_PARTY_ELIGIBLE` gating.
- ✅ 12-category rattan product taxonomy & B2B volume thresholds (10+ items = HoReCa).
- ✅ Competitor Demand Gap analytics (`unanswered_rate`, `b2b_gap`, `multi_source_gap`).
- ✅ 30-day Demand Heatmap analytics.
- ✅ Meta catalog mapping (`CatalogMapper`), 4 export recipes, SHA-256 privacy dry-run preview.
- ✅ Google Future Openings detection & manager review queue (`OpeningSignal`).

## 4. Features Claimed But Missing for V6

- ❌ Vertical context selector switch `[ Мебель ] [ Искусственный ротанг ]` in web navigation header.
- ❌ Immediate Telegram alert before AI analysis (currently notification waits for AI classification to complete).
- ❌ OpenAI Agents SDK integration & internal MCP tool gateway (`Lead Radar MCP Gateway`).
- ❌ Meta Marketing API live discovery catalog adapter (currently relies on static mapping dict).
- ❌ Google Places API grid coverage subdivision algorithm (currently text-extracted from comments).
- ❌ InterestVector decay & half-life background recalculation.
- ❌ Outcome learning feedback loop (linking won deals to pre-sale evidence to calibrate weights).
- ❌ Unit Economics dashboard (tracking API spend vs lead value/won deals).
- ❌ Dedicated UI subpage for Google Openings review queue (`/openings`).

## 5. Identified Risks & Bugs

1. **Immediate Notification Gap**: Current flow awaits AI analysis before sending Telegram notification. V6 requires immediate notification upon receiving a signal, followed by asynchronous message editing after AI analysis finishes.
2. **Missing MCP Gateway**: OpenAI integration uses raw `OpenAILeadAnalyzer` instead of Agents SDK with guarded tool calls and human approval.
3. **Missing Rattan Navigation Context**: Web UI does not isolate Rattan Resellers/Wholesalers into a dedicated vertical tab bar.
4. **Missing UI View for Openings**: Place openings are stored in DB and accessible via REST API (`/api/openings`), but lack a rendered Jinja template page.

## 6. Recommended Execution Plan (V6.0 – V6.17)

- **V6.0**: Complete pre-implementation audit documents and confirm compliance gates.
- **V6.1**: Event & Signal hardening (decay policy, backup runbook).
- **V6.2**: Immediate Telegram notification pipeline (instant alert -> async edit).
- **V6.3**: Intelligence V3 (EvidenceBundle, multi-score decomposition).
- **V6.4**: Audience Intelligence & Interest Engine (InterestVector decay, similarity engine, WON customer DNA).
- **V6.5**: Vertical UI & Rattan Intelligence (Vertical switch `[ Мебель ] [ Искусственный ротанг ]`, rattan reseller/wholesaler classifier).
- **V6.6**: Competitor Intelligence V3 (Commercial content score, opportunity engine).
- **V6.7**: Google Future Opening Radar (Google Places adapter, grid partition, `/openings` UI).
- **V6.8**: Meta Audience & Targeting Recipes (Meta interest search, 3 recipes NARROW/BALANCED/BROAD).
- **V6.9**: Google Marketing & Outcome Analytics (Google Ads search terms, GA4 summary).
- **V6.10**: Catalog & Next Best Action Engine (Catalog offer recommendations).
- **V6.11**: OpenAI Agent Core & Internal MCP Gateway (OpenAI Agents SDK, MCP tools, evals).
- **V6.12**: Guarded Write Tools (Human approval flows, audit log).
- **V6.13**: Telegram Bot 2.0 (Bot digests, conversational agent mode).
- **V6.14**: Premium Liquid-Glass UI Redesign (Design tokens, global search `Ctrl+K`, agent side drawer).
- **V6.15**: Unit Economics & Budget Controls (Spend vs ROI per channel).
- **V6.16**: Full Hardening & Quality Gate (132+ tests passed offline, ruff clean, data integrity OK).
- **V6.17**: Controlled Live Pilot Preparation.
