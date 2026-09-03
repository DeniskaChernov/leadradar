# Changelog

Формат: волны улучшений по `docs/SYSTEM_IMPROVEMENT_PLAN.md`. Полная история релизов — `RELEASE_NOTES.md`.

## [13.29.5-contrast] — 2026-09-03

### Added
- Playwright Chromium browser E2E: funnel take→CONTACTED→not-lead→reopen (`tests/e2e/test_leads_funnel_browser.py`)
- CI: `python -m playwright install --with-deps chromium`
- Audience membership unseen **v2**: 76 cases / 210 labeled decisions; gate threshold ≥160

### Fixed
- Audience unseen gate evaluates `{**criteria, vertical}` like production segment sync
- Duplicate unseen case_id `reactivated_contact`; rattan vs furniture vertical expectations

### Notes
- HTTP-level e2e smoke сохранён; локально после `pip install -r requirements.txt` нужен `python -m playwright install chromium`

## [13.29.3-bugfix] — 2026-09-02

### Fixed
- `move_lead` / kanban: нельзя закрыть WON/LOST без Deal (только win_deal/lose_deal)
- Kanban: колонки `ANALYZING` / `AI_PENDING` снова на доске
- Dashboard: при `revenue=None` показывается «—», не «0 сум»
- DnD: WON/LOST не drop-target; закрытые карточки без drag-handle; `dropInFlight` против гонок
- NEW/AI_* → TAKEN через stage: `MANAGER_ASSIGNED` + `AIFeedback.manager_is_lead`
- Meta Custom Audience: `num_invalid_entries` / short receive → ошибка, без EXPORTED
- Meta phone hash: единый E.164 UZ `998XXXXXXXXX` (dry-run sample = upload)
- Ops spend gate: `live_refresh` читает БД перед Instagram/OpenAI spend (multi-worker)

## [13.29.2-perf] — 2026-09-02

### Fixed
- Quality report: JOIN Lead↔Comment для `fresh_signal_clause` (убран SAWarning cartesian product)
- `/competitors`: batch `_competitor_stats_map` вместо N+1
- `/audiences`: один batch membership+intelligence вместо N+1 по сегментам
- `/leads` kanban: группировка `rows_by_stage` в Python (без O(stages×rows) в Jinja)

## [13.29.1-meta-export] — 2026-09-02

### Added
- Meta Custom Audience confirmed export: PAUSED audience + PHONE_SHA256 upload (`MetaAdsService.create_custom_audience`)
- Fail-closed without Meta live unlock; dry-run unchanged
- Pilot recommendation: `@aiko.uz` + `@chinar.uz`, ≤10 credits/scan

## [13.29.0-docs] — 2026-09-02

### Changed
- Phase 9 отмечена **offline ЗАВЕРШЁН** в `PROJECT_STATUS.md` / `ROADMAP.md`
- Добавлен `docs/POST_120_PLAN.md` и обновлён `docs/LIVE_PILOT_CHECKLIST.md`

## [13.29.0-wave18] — 2026-09-02

### Added
- Drag-and-drop kanban на `/leads` (desktop): handle ⠿, drop → `POST /api/leads/{id}/stage`
- План улучшений **120/120** закрыт

## [13.28.0-wave17] — 2026-09-02

### Added
- Unseen gate блокирует arm OpenAI live при FAIL (I5)
- Watch/off-catalog кейсы в `golden_lead_calibration.json` (I4)
- Dark mode tokens `@media (prefers-color-scheme: dark)` (D7)
- E2E smoke funnel `tests/e2e/test_leads_funnel_smoke.py` (I2)
- Load test concurrency очереди analyze (I6)
- `scripts/update_state_notes.py` (J2)
- Тест SIGTERM shutdown handler (J5)

## [13.27.0-wave16] — 2026-09-02

### Added
- Design tokens documentation block в `app.css` (D20)
- Restore drill в `BACKUP_RESTORE_RUNBOOK.md` (H5)
- `POSTGRESQL_MIGRATION_CHECKLIST.md` (H6)
- Regression test: «+» → OpenAI через `HybridLeadAnalyzer` (I7)
- Bugbot section в PR template (I10)
- `SENTRY_DSN` + `init_error_monitoring()` hook (J7)
- `docs/RAILWAY.md` deploy guide (J8)

## [13.27.0-wave15] — 2026-09-02

### Added
- PWA manifest и иконки (`/static/manifest.webmanifest`, `/static/icons/*`)
- Dedup `interest_evidence` при recalc (H7)
- Устойчивый `recalculate_all` — ошибка одного контакта не останавливает batch (H8)
- `CHANGELOG.md`, секция `WEB_MANAGER_ID` в `DEPLOYMENT.md`
- PR template и документ quality gates (I9)

## [13.26.0-wave14] — 2026-09-02

### Added
- Печать карточки лида (`@media print`, кнопка «Печать»)
- Страница сравнения конкурентов `/competitors/compare?left=&right=`
- Импорт конкурентов CSV/XLSX (`CompetitorImportService`, новые на паузе)
- Расширенный `/ready` (backup, reservations, competitors, queue)
- Runbook мусорных лидов: `docs/RUNBOOK_JUNK_LEADS.md`

## [13.25.0-wave13] — 2026-09-02

### Added
- `responsive-table` на radar/rattan/system
- Горячая клавиша `/` → фокус поиска
- Breadcrumbs на detail-страницах
- Aria-labels для accessibility
- `AgentRateLimitService` → HTTP 429
- `compact_contact_events()` на contact detail

## [13.24.0-wave12] — 2026-09-02

### Added
- Единый `.btn.tiny` (34px desktop, 40px mobile)
- Lucide empty states на detail-страницах
- Overlap graph SVG на `/competitors`
- Commercial rate trend + sparkline на competitor detail
- Кнопка «В заметку» на ответах агента
