# Lead Radar V4.1 — quality report

## Critical bugs found and fixed

- A new comment was notified only after analysis and only when it was HOT. AI failure could hide
  the signal from the manager. The pipeline is now Signal First.
- Telegram delivery had no explicit replay guard. Replay/mock now cannot send production alerts.
- Enrichment edit failure had no single-delivery fallback. A versioned, idempotent follow-up now
  covers that case.

## Minor bugs fixed

- Replay Telegram status could appear enabled even though the environment was cost-safe.
- Pending analysis was presented as a technical AI state instead of a manager-readable condition.
- Integrity checks did not include the new public-signal identity boundary.
- `ANALYZING` and retryable analysis states could not be taken into work by a manager.

## UX issues fixed

- The system page now explains the active notification mode in Russian.
- Each competitor can inherit the global mode or select all comments, commercial signals, or HOT.
- Radar, dashboard, lead list and lead detail explain active analysis without hiding the lead.
- Добавлен отдельный раздел динамических аудиторий с понятными агрегатами и campaign brief.
- Карточка клиента отделяет наблюдаемые публичные интересы от данных, введённых менеджером.
- Экспортное состояние явно показывает, почему контакт пока нельзя использовать вне CRM.

## Remaining known work

- Significant Change Detector and material-change alerts.
- Competitor Intelligence V2, opportunity analysis, demand gaps and overlap network.
- Global grouped search.
- Production validation of Telegram edit behavior with a live provider; automated tests currently
  use a deterministic fake bot and perform zero external calls.
- A dedicated device-emulation runner for exact 390 px Telegram Mini App screenshots. Responsive
  CSS remains covered by template/theme checks and desktop browser overflow checks.

## Verified quality gate

- `pytest`: 67 passed.
- `ruff check .`: passed.
- `compileall`: passed.
- Alembic: existing DB and a new empty DB both reached `b82f1d6a4c30`.
- Alembic autogenerate check: no pending operations.
- DB integrity: zero duplicate comments, posts, leads, public signals, audience profiles,
  memberships, deals and notification targets.
- Web smoke: 15 routes returned HTTP 200, including audience list and detail.
- Browser console: no warnings or errors.
- External Instagram/OpenAI calls: zero.
