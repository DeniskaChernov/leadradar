# Lead Radar — план улучшений (120 действий)

Статус: живой документ. `[x]` — сделано, `[ ]` — в очереди.

## A. Классификация сигналов и качество лидов (15)

- [x] A1. «+» → OpenAI по caption Reel
- [x] A2. Off-catalog (часы, телефоны) → NOT_LEAD локально
- [x] A3. Цена без контекста мебели → defer OpenAI
- [x] A4. Фикстуры watch_price + eval 208 сценариев
- [x] A5. API batch-переоценка лидов NEW
- [x] A6. Кнопка «Переоценить лиды» в Системе
- [ ] A7. Авто-переоценка после смены правил (version stamp)
- [ ] A8. Parent-comment context для reply «+»
- [ ] A9. Расширить off-catalog: украшения, обувь, техника
- [x] A10. UI-бейдж «Не наш ассортимент» на карточке лида
- [x] A11. Фильтр «мусорные лиды» на /leads
- [ ] A12. Метрика false-positive rate в /system
- [ ] A13. Feedback loop: NOT_LEAD → обучение правил
- [ ] A14. Re-analyze NOT_LEAD с score>50 (опционально)
- [ ] A15. Daily quality report в Telegram admin

## B. Воронка лидов и CRM (15)

- [x] B1. Kanban-кнопки воронки на /leads
- [x] B2. Toast «Сохранено · стадия»
- [x] B3. Баннер WEB_MANAGER_ID / trust save
- [ ] B4. Drag-and-drop kanban (optional phase 2)
- [x] B5. Bulk actions: взять / не лид
- [x] B6. Фильтр HOT + новые на доске
- [ ] B7. Сделки: связка WON из kanban переговоров
- [ ] B8. Задачи follow-up из карточки лида one-click
- [ ] B9. История contact_events на kanban tooltip
- [ ] B10. Mobile kanban swipe между колонками
- [ ] B11. Экспорт воронки CSV
- [ ] B12. SLA-бейдж «просрочен next_action»
- [ ] B13. Назначение менеджера в UI
- [ ] B14. Reopen NOT_LEAD из списка
- [x] B15. Воронка: колонки WON/LOST на доске

## C. Radar и мониторинг (12)

- [x] C1. Idle poll без location.reload
- [x] C2. Фильтр свежести 30 дней
- [x] C3. Одна кнопка «Оценить накопившееся»
- [x] C4. Plain-language help на всех вкладках radar
- [ ] C5. Счётчик «спорных» vs «архив» раздельно
- [ ] C6. Preview стоимости scan до запуска (улучшить)
- [ ] C7. Post-scan summary modal
- [ ] C8. Competitor tier в строке radar feed
- [x] C9. Quick filter: только HOT actionable
- [ ] C10. WebSocket/poll status bar global
- [ ] C11. Pause search banner если LEAD_SEARCH_ENABLED=false
- [ ] C12. Radar empty state с CTA «включить live»

## D. UI/UX и дизайн (20)

- [x] D1. hero-status на основных страницах
- [x] D2. Cache-bust 13.11.7-leads-funnel
- [x] D3. Economics plain-language hero
- [x] D4. Competitors plain-language hero
- [ ] D5. Agent page: preset chips RU
- [x] D6. Единый `.plain-help` блок на всех hero
- [ ] D7. Dark mode tokens (optional)
- [ ] D8. Унифицировать `.btn.tiny` размеры
- [ ] D9. Table mobile: все страницы responsive-table
- [ ] D10. Empty states lucide везде
- [ ] D11. Loading skeletons для kanban
- [ ] D12. Confirm modal RU для destructive
- [ ] D13. Toast stack + undo NOT_LEAD
- [ ] D14. Focus restore после reloadSoon
- [ ] D15. Keyboard shortcuts (/ search)
- [ ] D16. Breadcrumbs на detail pages
- [ ] D17. Print-friendly lead card
- [ ] D18. PWA manifest + icons
- [ ] D19. Accessibility audit aria-labels
- [ ] D20. Design tokens doc в CSS :root

## E. Экономика и бюджет (10)

- [x] E1. Economics hero: «сколько потратили / сколько лидов»
- [ ] E2. Plain labels вместо PROVIDER_CONFIRMED
- [ ] E3. График burn 7d sparkline
- [ ] E4. Alert если credits < 20% месяца
- [ ] E5. Cost per HOT lead KPI
- [ ] E6. OpenAI $/lead metric
- [ ] E7. Export economics CSV
- [ ] E8. Link economics → radar budget
- [ ] E9. ROI placeholder (deals revenue)
- [ ] E10. Budget simulation slider

## F. Конкуренты и discovery (10)

- [x] F1. Competitors hero короче + KPI glass
- [ ] F2. Рекомендация tier auto-suggest UI
- [ ] F3. Bulk pause/resume competitors
- [ ] F4. Discovery → add competitor flow
- [ ] F5. Overlap graph visual
- [ ] F6. Commercial rate trend per competitor
- [ ] F7. Last scan error badge
- [ ] F8. Notification policy plain RU
- [ ] F9. Competitor compare side-by-side
- [ ] F10. Import CSV competitors

## G. AI, agent, OpenAI (10)

- [ ] G1. Agent: контекст лида в каждом preset
- [x] G2. Agent: «почему не лид» preset
- [ ] G3. GPT queue progress в header
- [ ] G4. OpenAI cost per analysis in lead detail
- [ ] G5. Cache hit rate metric
- [ ] G6. Prompt version display
- [ ] G7. Manual «переспросить GPT» для NEW
- [ ] G8. Agent export answer to note
- [ ] G9. Rate limit user feedback
- [ ] G10. Fallback message если GPT off

## H. Данные и миграции (8)

- [x] H1. Script reclassify_existing_leads.py
- [ ] H2. Integrity: leads без comment
- [ ] H3. Archive baseline comments UI filter
- [ ] H4. contact_events compaction view
- [ ] H5. Backup restore drill doc
- [ ] H6. PostgreSQL prod migration checklist
- [ ] H7. interest_evidence duplicate fix
- [ ] H8. Audience recalc error handling

## I. Тесты и quality gates (10)

- [x] I1. Tests funnel UI + signal scope
- [ ] I2. E2E smoke Playwright /leads funnel
- [x] I3. API test reanalyze-batch
- [ ] I4. Golden dataset + watch cases
- [ ] I5. Unseen gate после rule change
- [ ] I6. Load test analyze queue
- [ ] I7. Regression: plus → OpenAI mock
- [ ] I8. Web theme test 13.12.x
- [ ] I9. CI: ruff + pytest mandatory
- [ ] I10. Bugbot on PR template

## J. Ops, deploy, docs (10)

- [ ] J1. PROJECT_STATUS sync
- [ ] J2. State.md machine notes auto
- [ ] J3. DEPLOYMENT.md WEB_MANAGER_ID
- [ ] J4. Health /ready расширенный
- [ ] J5. Graceful shutdown verify
- [ ] J6. Log structured JSON option
- [ ] J7. Sentry hook placeholder
- [ ] J8. Railway/Railpack doc
- [ ] J9. Runbook: «мусор в лидах»
- [ ] J10. Changelog per release

---

**Текущий спринт (волна 1):** A5–A6, D3–D4, E1, F1, I3, J1.
