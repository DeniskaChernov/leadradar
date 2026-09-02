# Lead Radar — план улучшений (120 действий)

Статус: живой документ. `[x]` — сделано, `[ ]` — в очереди.

## A. Классификация сигналов и качество лидов (15)

- [x] A1. «+» → OpenAI по caption Reel
- [x] A2. Off-catalog (часы, телефоны) → NOT_LEAD локально
- [x] A3. Цена без контекста мебели → defer OpenAI
- [x] A4. Фикстуры watch_price + eval 218 сценариев
- [x] A5. API batch-переоценка лидов NEW
- [x] A6. Кнопка «Переоценить лиды» в Системе
- [x] A7. Авто-переоценка после смены правил (version stamp)
- [x] A8. Parent-comment context для reply «+»
- [x] A9. Расширить off-catalog: украшения, обувь, техника
- [x] A10. UI-бейдж «Не наш ассортимент» на карточке лида
- [x] A11. Фильтр «мусорные лиды» на /leads
- [x] A12. Метрика false-positive rate в /system
- [x] A13. Feedback loop: NOT_LEAD → обучение правил
- [x] A14. Re-analyze NOT_LEAD с score>50 (опционально)
- [x] A15. Daily quality report в Telegram admin

## B. Воронка лидов и CRM (15)

- [x] B1. Kanban-кнопки воронки на /leads
- [x] B2. Toast «Сохранено · стадия»
- [x] B3. Баннер WEB_MANAGER_ID / trust save
- [x] B4. Drag-and-drop kanban (optional phase 2)
- [x] B5. Bulk actions: взять / не лид
- [x] B6. Фильтр HOT + новые на доске
- [x] B7. Сделки: связка WON из kanban переговоров
- [x] B8. Задачи follow-up из карточки лида one-click
- [x] B9. История contact_events на kanban tooltip
- [x] B10. Mobile kanban swipe между колонками
- [x] B11. Экспорт воронки CSV
- [x] B12. SLA-бейдж «просрочен next_action»
- [x] B13. Назначение менеджера в UI
- [x] B14. Reopen NOT_LEAD из списка
- [x] B15. Воронка: колонки WON/LOST на доске

## C. Radar и мониторинг (12)

- [x] C1. Idle poll без location.reload
- [x] C2. Фильтр свежести 30 дней
- [x] C3. Одна кнопка «Оценить накопившееся»
- [x] C4. Plain-language help на всех вкладках radar
- [x] C5. Счётчик «спорных» vs «архив» раздельно
- [x] C6. Preview стоимости scan до запуска (улучшить)
- [x] C7. Post-scan summary modal
- [x] C8. Competitor tier в строке radar feed
- [x] C9. Quick filter: только HOT actionable
- [x] C10. WebSocket/poll status bar global
- [x] C11. Pause search banner если LEAD_SEARCH_ENABLED=false
- [x] C12. Radar empty state с CTA «включить live»

## D. UI/UX и дизайн (20)

- [x] D1. hero-status на основных страницах
- [x] D2. Cache-bust 13.11.7-leads-funnel
- [x] D3. Economics plain-language hero
- [x] D4. Competitors plain-language hero
- [x] D5. Agent page: preset chips RU
- [x] D6. Единый `.plain-help` блок на всех hero
- [x] D7. Dark mode tokens (optional)
- [x] D8. Унифицировать `.btn.tiny` размеры
- [x] D9. Table mobile: все страницы responsive-table
- [x] D10. Empty states lucide везде
- [x] D11. Loading skeletons для kanban
- [x] D12. Confirm modal RU для destructive
- [x] D13. Toast stack + undo NOT_LEAD
- [x] D14. Focus restore после reloadSoon
- [x] D15. Keyboard shortcuts (/ search)
- [x] D16. Breadcrumbs на detail pages
- [x] D17. Print-friendly lead card
- [x] D18. PWA manifest + icons
- [x] D19. Accessibility audit aria-labels
- [x] D20. Design tokens doc в CSS :root

## E. Экономика и бюджет (10)

- [x] E1. Economics hero: «сколько потратили / сколько лидов»
- [x] E2. Plain labels вместо PROVIDER_CONFIRMED
- [x] E3. График burn 7d sparkline
- [x] E4. Alert если credits < 20% месяца
- [x] E5. Cost per HOT lead KPI
- [x] E6. OpenAI $/lead metric
- [x] E7. Export economics CSV
- [x] E8. Link economics → radar budget
- [x] E9. ROI placeholder (deals revenue)
- [x] E10. Budget simulation slider

## F. Конкуренты и discovery (10)

- [x] F1. Competitors hero короче + KPI glass
- [x] F2. Рекомендация tier auto-suggest UI
- [x] F3. Bulk pause/resume competitors
- [x] F4. Discovery → add competitor flow
- [x] F5. Overlap graph visual
- [x] F6. Commercial rate trend per competitor
- [x] F7. Last scan error badge
- [x] F8. Notification policy plain RU
- [x] F9. Competitor compare side-by-side
- [x] F10. Import CSV competitors

## G. AI, agent, OpenAI (10)

- [x] G1. Agent: контекст лида в каждом preset
- [x] G2. Agent: «почему не лид» preset
- [x] G3. GPT queue progress в header
- [x] G4. OpenAI cost per analysis in lead detail
- [x] G5. Cache hit rate metric
- [x] G6. Prompt version display
- [x] G7. Manual «переспросить GPT» для NEW
- [x] G8. Agent export answer to note
- [x] G9. Rate limit user feedback
- [x] G10. Fallback message если GPT off

## H. Данные и миграции (8)

- [x] H1. Script reclassify_existing_leads.py
- [x] H2. Integrity: leads без comment
- [x] H3. Archive baseline comments UI filter
- [x] H4. contact_events compaction view
- [x] H5. Backup restore drill doc
- [x] H6. PostgreSQL prod migration checklist
- [x] H7. interest_evidence duplicate fix
- [x] H8. Audience recalc error handling

## I. Тесты и quality gates (10)

- [x] I1. Tests funnel UI + signal scope
- [x] I2. E2E smoke Playwright /leads funnel
- [x] I3. API test reanalyze-batch
- [x] I4. Golden dataset + watch cases
- [x] I5. Unseen gate после rule change
- [x] I6. Load test analyze queue
- [x] I7. Regression: plus → OpenAI mock
- [x] I8. Web theme test 13.12.x
- [x] I9. CI: ruff + pytest mandatory
- [x] I10. Bugbot on PR template

## J. Ops, deploy, docs (10)

- [x] J1. PROJECT_STATUS sync
- [x] J2. State.md machine notes auto
- [x] J3. DEPLOYMENT.md WEB_MANAGER_ID
- [x] J4. Health /ready расширенный
- [x] J5. Graceful shutdown verify
- [x] J6. Log structured JSON option
- [x] J7. Sentry hook placeholder
- [x] J8. Railway/Railpack doc
- [x] J9. Runbook: «мусор в лидах»
- [x] J10. Changelog per release

---

**Текущий спринт (волна 4):** A9, B7–B8, B12, B14, C5, C11, D5, E2, J1.
