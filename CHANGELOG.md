# Changelog

Формат: волны улучшений по `docs/SYSTEM_IMPROVEMENT_PLAN.md`. Полная история релизов — `RELEASE_NOTES.md`.

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
