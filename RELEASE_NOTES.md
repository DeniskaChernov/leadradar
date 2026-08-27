# Lead Radar V4.1 Foundation — release notes

## V4.1 Foundation · Significant Change Detector

- новые сигналы сравниваются с предыдущим коммерческим профилем после Audience Engine;
- уведомляются только существенные переходы: новый конкурент/intent/товар, B2B, количество,
  HOT/high-value, реактивация, новая стадия или большой рост приоритета;
- одно событие группирует несколько причин и сохраняет понятное сравнение «было → стало»;
- отдельный retry-safe Telegram outbox не допускает повторной доставки одному менеджеру;
- Command Center и карточка клиента показывают объяснимые изменения без vanity score noise;
- миграция `c93a1f7d2e40` проверена на рабочей и пустой БД;
- 72 теста, Ruff, compileall, integrity scan и browser smoke прошли без внешних вызовов.

## V4.1 Foundation · Audience Engine

- добавлены наблюдаемые коммерческие профили для каждого контакта;
- 20 динамических аудиторий пересчитываются идемпотентно из сохранённых сигналов;
- появились отдельные страницы аудиторий, состав сегмента и campaign brief на реальных данных;
- карточка клиента показывает стадию, активность, ценность, интересы и активные сегменты;
- username не разрешает экспорт; first-party eligibility требует телефон и подтверждённую
  квалификацию менеджером;
- миграция `b82f1d6a4c30`, 25 профилей и 500 membership проверены без дублей;
- 67 тестов, Ruff, compileall, integrity scan и web/browser smoke прошли без внешних вызовов.

## V4.1 Foundation · Signal First

- новый комментарий сохраняется как уникальный `PublicSignal` до любых внешних действий;
- первый Telegram-сигнал отправляется до AI, enrichment и profile analysis;
- сообщение после анализа редактируется на месте, с идемпотентным concise fallback;
- появились режимы уведомлений для всей системы и отдельного конкурента;
- baseline и replay гарантированно не отправляют production-уведомления;
- сбой AI оставляет менеджеру рабочий лид со статусом «Нужна дополнительная проверка»;
- новая миграция проверена на существующей и пустой БД;
- 62 теста, Ruff, compileall, integrity scan и 13 web routes прошли без внешних вызовов.

## V3.5 · deep lead intelligence

- AI-анализ теперь возвращает уверенность, стадию покупки, срочность, горизонт, доказательства,
  риски и лучшее следующее действие;
- усилены отрицания, смешанные намерения, ценовые возражения и RU/UZ urgency-сигналы;
- OpenAI Responses использует Structured Outputs, reasoning `medium`, `store=false` и новый cache key;
- добавлена миграция `f31a8c74d920` и идемпотентный локальный backfill;
- все 28 существующих результатов получили расширенное объяснение без OpenAI;
- карточка лида получила отдельный intelligence-блок;
- Radar адаптируется в карточки на узких экранах;
- 57 тестов пройдены, внешние Instagram/OpenAI вызовы не выполнялись.

## V3.4 · light liquid-glass interface

- Mini App получил единую светлую glass-систему для всех страниц;
- подключена лёгкая библиотека Lucide 1.34.0 для навигационных SVG-иконок;
- добавлены стеклянные панели с graceful fallback для старых браузеров;
- улучшены контраст, keyboard focus, skip navigation и reduced-motion режим;
- статические ассеты переведены на cache key `v=3.4`;
- поиск лидов и внешние AI/Instagram вызовы остались выключены.

## V3.3 · lead operations

- локально квалифицированы сохранённые сигналы без OpenAI;
- усилены RU / UZ Latin / UZ Cyrillic правила покупки, цены, рассрочки и HoReCa;
- Telegram outbox работает независимо от паузы поиска и направляет лид назначенному менеджеру;
- добавлены пять проверенных компаний, всего 16, новые аккаунты остаются на паузе;
- Dashboard и Radar показывают операционную очередь и качество классификации;
- Instagram/OpenAI остаются заблокированы через `LEAD_SEARCH_ENABLED=false` и live guards.

## V3.2 · market intelligence

## Главная тема релиза

**AIKO → карта мебельного рынка.**

V3.2 добавляет отдельный market-intelligence слой и делает расширение конкурентов безопасным для
внешних лимитов.

## Добавлено

- 11 подтверждённых Instagram-конкурентов в радаре;
- 27 market candidates;
- market catalog sync;
- новые competitors всегда на паузе, кроме уже активного AIKO;
- website/catalog metadata у конкурента;
- confidence и rationale у market candidate;
- добавление кандидата в мониторинг из Mini App;
- HOT-rate и рекомендация приоритета источника;
- cross-competitor customer signal;
- дополнительный ограниченный score boost, если человек сравнивает нескольких продавцов;
- новый раздел «Развитие» и ROADMAP.md;
- текущая стадия проекта на Dashboard.

## Проверено перед релизом

- 49 pytest tests passed;
- compileall passed;
- V3.2 Alembic migration passed on copy of existing SQLite DB;
- catalog sync: 11 competitors, 27 candidates, only AIKO active;
- primary V3.2 web pages smoke-tested against migrated DB;
- 0 live Instagram/OpenAI calls were used during development.

## Важная экономическая защита

Расширение карты рынка не равно расширению платного мониторинга. Все новые аккаунты стартуют
paused. Включать live нужно постепенно после preview бюджета и контрольного теста качества.

## MVP safety patch before packaging

- фоновый мониторинг теперь opt-in: `MONITOR_SCHEDULE_ENABLED=false` по умолчанию;
- простое открытие Mini App больше не запускает replay/live polling автоматически;
- ручной scan остаётся доступен;
- для фоновой live-работы нужно отдельно включить `MONITOR_SCHEDULE_ENABLED=true` и снять режим `INSTAGRAM_MANUAL_LIVE_SCAN_ONLY`;
- packaged SQLite мигрирована до `e2c7a4f91b20` и содержит 11 competitors / 27 market candidates;
- финальный smoke-test подтвердил, что web-only запуск не изменяет число комментариев в основной базе.
