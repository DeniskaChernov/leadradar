# Runbook: «мусор в лидах»

Краткий алгоритм, когда в воронке много ложных HOT/NEW или off-catalog сигналов.

## 1. Диагностика

1. Откройте `/leads` → фильтр **«Не наш товар»** и **NOT_LEAD** — оцените долю отсеянных сигналов.
2. `/system` → блок quality / false-positive rate и daily quality report (Telegram admin).
3. `/radar` → проверьте источник: один конкурент или весь рынок.
4. `/economics` → не тратятся ли credits на переоценку мусора.

## 2. Быстрые действия менеджера

- Карточка лида → **NOT_LEAD** (история сохраняется в `contact_events`).
- Toast **«Отменить»** 8 сек — если ошиблись.
- Фильтр `/leads?status=NOT_LEAD` + **reanalyze** для score≥50 (волна 9).

## 3. Обучение правил

- `/system` → feedback loop (NOT_LEAD → export rules).
- `GET /api/system/feedback-export` — выгрузка для анализа паттернов.
- После смены rules: **переоценка NEW** (`/system` → batch reanalyze).

## 4. Профилактика

- Off-catalog локально: часы, телефоны, украшения — без GPT.
- Parent-comment для reply «+» — контекст Reel caption.
- Daily quality report в Telegram — следить за drift.

## 5. Когда эскалировать

- Рост NOT_LEAD >30% за неделю при стабильных источниках.
- HOT false-positive в `/audiences/quality`.
- Drift unseen gates на `/system` — не включать live GPT до PASS.

## 6. Нельзя

- Удалять строки из БД.
- Массово менять статусы без `contact_events`.
- Коммитить secrets или включать live API без `/ready` = 200.
