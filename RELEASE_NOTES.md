# Lead Radar V3.3 — release notes

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
