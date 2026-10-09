# Lead Radar — реестр возможностей

Обновлено: 2026-10-09. Основание: код `39425c0`, диагностика/восстановление
и этап продолжения публикаций 9 октября. HTTP 200, наличие кнопки или mock-тест сами по себе
не доказывают действующую внешнюю интеграцию.

Работает — сценарий реализован и проверяется. Частично — есть указанное ограничение.
Требует настройки — код есть, данных/режима нет. Не подключено — нет рабочего
потока получения внешних данных. Имена проверок — файлы в tests/ без суффикса .py.

| Раздел / действие | Состояние | Возможность и ограничение | Проверка / следующий шаг |
| --- | --- | --- | --- |
| Вход, выход, роли, CSRF | Работает | Пароль admin и Telegram auth; общий пароль не создаёт персональные аккаунты | test_password_auth, test_web_security; R5.5 |
| Обзор | Работает | Сводка БД и ссылки к сценариям | test_qa_smoke_pages, test_system_pages_browser_20261008 |
| Радар: preview, запуск, прогресс, отмена | Работает | Ручной режим, budget, запрет параллельного запуска, частичные результаты | test_live_scan_guard, test_scan_progress, test_comment_capture_reliability |
| Публикации источника | Реализовано, live-приёмка открыта | Фото/карусели/reels; отдельные страницы, сохранённый provider cursor, бюджет и очередь комментариев | test_post_discovery; R2.1/R2.2 закрыты, R2.6 открыт |
| Родительские комментарии | Работает с ограничениями | Backfill, head refresh, repeated cursor, FULL/PARTIAL/UNKNOWN | test_head_refresh_during_backfill, test_workflow_pass_20261008; R2.3 |
| Вложенные ответы | Не подключено к сбору | Parent context при доступных фактах; отдельного обхода replies нет | include_replies=false; R2.4 |
| HOT: взять, черновик, отметить отправку, следующий | Работает | Повторы и владелец защищены; копирование не отправляет Instagram-сообщение | test_hot_committed_results, test_hot_outreach, test_hot_workspace_browser |
| HOT: поиск | Частично | По текущей странице | test_ux_workflow_20261008; R5.1 |
| Лиды: список, канбан, фильтры, массовые действия | Работает | Пагинация/счётчики; доска относится к выбранной странице | test_system_pass_20261008, test_wave10_kanban |
| Карточка лида: история, explain, переоценка | Работает | Вся история по страницам; ручное решение сохраняется | test_workflow_pass_20261008, test_analysis_workflow_decisions |
| Клиенты: квалификация, назначение, заметка, ответ | Работает | Идемпотентные записи, числовая валидация, immutable history | test_workflow_pass_20261008, test_crm_workflow_consistency |
| История, сигналы, заметки клиента | Работает | Независимые страницы и стабильный порядок | test_workflow_pass_20261008 |
| Лиды, задачи, сделки внутри карточки клиента | Частично | Выборки ещё без отдельной пагинации | queries.contact_detail; R5.4 |
| Задачи: создать, перенести, завершить, отменить | Работает | Повторы, срок, просрочка, пагинация; рабочих задач пока 0 | test_crm_workflow_consistency, test_system_pass_20261008; R5.4 |
| Сделки: предложение, продажа, отказ, возврат | Работает | Стадии, валюта, количество и снимки; рабочих сделок пока 0 | test_lead_workflow, test_crm_workflow_consistency |
| CSV лидов/экономики | Работает | Все строки выборки; корректные счётчики | test_system_pass_20261008, test_economics_phase4 |
| Источники: импорт, пауза, направление, свежесть | Работает | Настройки из БД без restart; ограниченный активный мебельный портфель | test_competitor_intelligence; R3 |
| Ротанг | Требует настройки | Отдельная логика; активных источников нет | test_rattan_vertical_v2; R3.2 |
| Discovery: импорт и review | Работает | Локальные snapshots, изменения и модерация кандидатов | test_discovery_service |
| Discovery: широкий внешний поиск | Не подключено | Автоматический Google/Maps/маркетплейсы-поиск отсутствует | DISCOVERY_CENTER; R3.5/R10.3 |
| Новые заведения | Работает с ограничениями | Идемпотентная подача из лидов; независимого Maps-поиска нет | test_openings_and_hot_pagination, test_place_openings; R10.4 |
| Каталог: seed, BTT, импорт, подтверждение | Работает | Датированный снимок, источники, валюта, ручные факты защищены | test_public_catalog_import, test_product_catalog |
| Каталог: актуальные цены, склад, условия | Частично | Нет постоянной синхронизации; количественный склад/COGS не подтверждён | HARDENING_2026-10-06; R6 |
| Подбор товара/следующего действия | Работает с ограничениями | Факты из БД; без совпадения — уточнение потребности | test_next_best_action; R6.4 |
| Квалификация и AI-очередь | Работает | Правила, budget, cache, retries/lease; качество по продажам ещё не измерено | test_ai_pending, test_ai_idempotency, test_lead_analysis_pipeline; R4 |
| Экономика, тарифы, FX | Работает с ограничениями | Учёт и настройка цен; деньги зависят от тарифов/COGS | test_economics_phase4, test_spend_semantics_hardening; R8 |
| Аудитории, качество, рецепты | Работает с ограничениями | Локальные сегменты/происхождение; рекламный запуск выключен | test_audience_registry_v4, test_export_recipes; R10.5 |
| Агент: инструменты БД | Работает с ограничениями | История и approval; не универсальный AI-планировщик | test_agent_chat_persistence, test_mcp_write_tools; R10.2 |
| Telegram polling/outbox | Требует настройки режима | Текущий сервер web-only; отправка этим этапом не подтверждается | test_notifications, test_notification_readiness; R10.1 |
| Meta Ads | Требует настройки | Adapter/валидация/экспорт; live выключен | test_meta_ads_service, test_meta_audience_foundation; R10.5 |
| Google marketing | Не подключено к получению данных | Локальная обработка переданных метрик | google_marketing_service; R10.3 |
| Другие платформы | Не подключено | Пункт UI/adapter не доказывает рабочий сбор комментариев | R10.3: отдельный ограниченный пилот |
| /health, /ready | Работает | Процесс и БД/миграции; живой provider API не проверяется | test_deployment_readiness; R1.3 |
| Диагностика процесса | Работает, новый этап | PID/run/build, heartbeat и завершение; SQLite файл, PostgreSQL память | test_recovery_foundation; launcher/tunnel R1.1 ещё частично |
| Backup/restore SQLite | Работает, новый этап | Online snapshot, validation, atomic replace, runtime lock, original preservation | test_recovery_foundation; live-copy drill |
| Windows launcher/tunnel | Работает с ограничениями | Ownership, reuse, cleanup; реальный reboot не проверен | test_windows_runtime; R1.4 |
| Cloudflare | Работает с ограничениями | Временный доступ с auth; сервер на Windows | LIVE_SETUP_2026-10-06; R9 |
| PostgreSQL/автономный хост | Не развёрнуто в рабочем экземпляре | CI/config есть; ownership и cutover предстоят | R9.3–R9.5 |
| GitHub CI | Настроено | SQLite/Postgres matrix; green status текущего commit не проверен | CI_QUALITY_GATES; этап 9 |

## Следующие задачи и условия отката

| Задача | Пользовательский результат | Приёмка | Условие отката |
| --- | --- | --- | --- |
| R2.1/R2.2 | Следующие страницы публикаций | Replay с двумя страницами/рестартом и общий budget | Перерасход/потеря позиции |
| R2.3 | Понятна причина неполного сбора | Все терминальные причины в UI | Неподтверждённая полнота |
| R5.1 | Клиент находится на любой странице HOT | 81+ клиентов, фильтры/черновик | Пропуск доступного клиента/потеря текста |
| R4.1/R4.2 | HOT объясним и оценён | Независимые размеченные случаи | Отмена ручных решений/регрессия качества |
| R6.1–R6.3 | Видна свежесть фактов каталога | Preview, повтор, конфликт ручного значения | Перезапись подтверждённого без review |
| R9.3–R9.5 | Работа без личного компьютера | Ownership, перенос, сверка, откат | Несовпадение истории/расходов, два scans |

Датированные аудиты сохраняются как исторические свидетельства. Актуальные
доказательства: WORKFLOW_PASS, SYSTEM_PASS, UX_REVIEW за 2026-10-08,
HARDENING_2026-10-06 и RECOVERY_FOUNDATION_2026-10-08.

## Подготовка R2.1/R2.2 от 8 октября (история)

Реализация от 9 октября: [POST_DISCOVERY_2026-10-09.md](POST_DISCOVERY_2026-10-09.md).
Ниже сохранена исходная постановка; это не описание текущего ограничения первой страницы.

Проблема подтверждена кодом: `get_reels` возвращает только список первой
страницы `/v2/instagram/user/posts`; курсор списка публикаций не передаётся
монитору и не сохраняется в БД. Комментарии имеют отдельную пагинацию.
У провайдера документированы `next_max_id` и `more_available`:
[ScrapeCreators User Posts API](https://docs.scrapecreators.com/v2/instagram/user/posts/).
Документация проверена 2026-10-08; платный запрос не выполнялся.

Следующее изменение должно включать единый результат страницы публикаций,
сохранённое продолжение по источнику/провайдеру, лимит возраста и числа страниц,
отдельную проверку новых публикаций и честную причину неполного обхода.
Результат страницы и курсор сохраняются одной транзакцией после валидации.
Повтор после сбоя не создаёт второй post/signal/lead.

Затрагиваемые файлы: `app/providers/base.py`, `scrapecreators.py`, `budgeted.py`,
`fallback.py`, `replay.py`, `mock.py`, `brightdata.py`; `app/schemas/instagram.py`,
`app/services/instagram_monitor.py`, `adaptive_monitoring_service.py`,
модель/миграция состояния discovery, `app/web/queries.py` и UI покрытия.

Зависимости: проверенный backup/restore этого этапа, provider-specific cursor
и общий ScanBudget. В `BudgetedInstagramProvider._call` резервируется одна
логическая операция: нельзя спрятать обход нескольких платных страниц внутри
старого `get_reels`. Каждая запрошенная страница должна быть зарезервирована
до вызова; неоднозначный расход не запускает fallback. Страница публикаций
не должна вытеснять весь доступный бюджет комментариев. Ручной предел 5 сохраняется.

Приёмка: replay двух страниц; новый post в начале при незавершённом доборе;
повтор/restart после сохранения страницы; repeated cursor; пустой/ошибочный
ответ; чужой provider cursor; privacy; отмена; budget 0/1/5 с отдельным учётом
вызовов/расходов; отсутствие дублей и сохранность contact_events.
Откат: несовпадение истории/расходов, потеря позиции или скрытые платные вызовы.
Начальный режим обхода — выключен до offline-приёмки; старый рабочий сбор остаётся
доступным. Это подготовленная задача, а не уже включённая возможность.

## HTTP-маршруты

Инвентаризация декораторов исходного кода: 94 маршрутов.
Это карта связи адреса с обработчиком; наличие маршрута само по себе
не означает проверку внешней интеграции. Состояния сценариев приведены выше.

| Метод | Адрес | Обработчик | Исходник |
| --- | --- | --- | --- |
| GET | `/sw.js` | `service_worker_script` | [app/web/app.py:154](../app/web/app.py#L154) |
| GET | `/auth` | `auth_page` | [app/web/app.py:461](../app/web/app.py#L461) |
| POST | `/api/auth/password` | `password_auth` | [app/web/app.py:481](../app/web/app.py#L481) |
| POST | `/api/auth/telegram` | `telegram_auth` | [app/web/app.py:512](../app/web/app.py#L512) |
| POST | `/logout` | `logout` | [app/web/app.py:521](../app/web/app.py#L521) |
| GET | `/` | `dashboard` | [app/web/app.py:527](../app/web/app.py#L527) |
| GET | `/rattan` | `rattan_workspace` | [app/web/app.py:536](../app/web/app.py#L536) |
| GET | `/radar` | `radar` | [app/web/app.py:545](../app/web/app.py#L545) |
| GET | `/hot` | `hot_workspace` | [app/web/app.py:583](../app/web/app.py#L583) |
| POST | `/api/hot/{lead_id}/prepare` | `hot_prepare` | [app/web/app.py:646](../app/web/app.py#L646) |
| POST | `/api/hot/{lead_id}/sent` | `hot_mark_sent` | [app/web/app.py:663](../app/web/app.py#L663) |
| POST | `/api/hot/{lead_id}/draft` | `hot_save_draft` | [app/web/app.py:689](../app/web/app.py#L689) |
| GET | `/leads` | `leads` | [app/web/app.py:716](../app/web/app.py#L716) |
| GET | `/api/leads/export.csv` | `export_leads_csv` | [app/web/app.py:762](../app/web/app.py#L762) |
| GET | `/leads/{lead_id}` | `lead_detail` | [app/web/app.py:820](../app/web/app.py#L820) |
| GET | `/catalog` | `catalog` | [app/web/app.py:843](../app/web/app.py#L843) |
| GET | `/contacts` | `contacts` | [app/web/app.py:857](../app/web/app.py#L857) |
| GET | `/contacts/{contact_id}` | `contact_detail` | [app/web/app.py:867](../app/web/app.py#L867) |
| GET | `/tasks` | `tasks` | [app/web/app.py:887](../app/web/app.py#L887) |
| GET | `/deals` | `deals` | [app/web/app.py:897](../app/web/app.py#L897) |
| GET | `/analytics` | `analytics` | [app/web/app.py:908](../app/web/app.py#L908) |
| GET | `/economics` | `economics` | [app/web/app.py:919](../app/web/app.py#L919) |
| GET | `/api/economics/export.csv` | `export_economics_csv` | [app/web/app.py:933](../app/web/app.py#L933) |
| GET | `/audiences` | `audiences` | [app/web/app.py:975](../app/web/app.py#L975) |
| GET | `/audiences/quality` | `audience_quality` | [app/web/app.py:984](../app/web/app.py#L984) |
| GET | `/audiences/{slug}` | `audience_detail` | [app/web/app.py:993](../app/web/app.py#L993) |
| GET | `/competitors` | `competitors` | [app/web/app.py:1017](../app/web/app.py#L1017) |
| GET | `/discovery` | `discovery` | [app/web/app.py:1039](../app/web/app.py#L1039) |
| GET | `/competitors/compare` | `competitors_compare` | [app/web/app.py:1064](../app/web/app.py#L1064) |
| GET | `/competitors/{competitor_id}` | `competitor_detail` | [app/web/app.py:1080](../app/web/app.py#L1080) |
| GET | `/openings` | `openings` | [app/web/app.py:1091](../app/web/app.py#L1091) |
| GET | `/roadmap` | `roadmap` | [app/web/app.py:1106](../app/web/app.py#L1106) |
| GET | `/system` | `system` | [app/web/app.py:1114](../app/web/app.py#L1114) |
| POST | `/api/pricing` | `set_pricing` | [app/web/app.py:1257](../app/web/app.py#L1257) |
| POST | `/api/pricing/fx` | `set_fx_rate` | [app/web/app.py:1291](../app/web/app.py#L1291) |
| POST | `/api/replay/advance` | `replay_advance` | [app/web/app.py:1310](../app/web/app.py#L1310) |
| POST | `/api/replay/reset` | `replay_reset` | [app/web/app.py:1322](../app/web/app.py#L1322) |
| GET | `/api/scan/preview` | `scan_preview` | [app/web/app.py:1462](../app/web/app.py#L1462) |
| POST | `/api/scan` | `scan_now` | [app/web/app.py:1474](../app/web/app.py#L1474) |
| POST | `/api/ops/radar-live` | `set_radar_live` | [app/web/app.py:1527](../app/web/app.py#L1527) |
| POST | `/api/ops/openai-live` | `set_openai_live` | [app/web/app.py:1564](../app/web/app.py#L1564) |
| POST | `/api/ops/ai-concurrency` | `set_ai_concurrency` | [app/web/app.py:1597](../app/web/app.py#L1597) |
| POST | `/api/notifications/uncertain/{kind}/{log_id}/resolve` | `resolve_uncertain_notification` | [app/web/app.py:1621](../app/web/app.py#L1621) |
| POST | `/api/budget/reservations/{reservation_id}/reconcile` | `reconcile_budget_reservation` | [app/web/app.py:1678](../app/web/app.py#L1678) |
| POST | `/api/signals/review-all` | `review_all_signals` | [app/web/app.py:1716](../app/web/app.py#L1716) |
| POST | `/api/history/analyze-local` | `analyze_history_local` | [app/web/app.py:1762](../app/web/app.py#L1762) |
| POST | `/api/leads/retry-pending` | `retry_pending_leads` | [app/web/app.py:1778](../app/web/app.py#L1778) |
| POST | `/api/leads/reanalyze-batch` | `reanalyze_leads_batch` | [app/web/app.py:1818](../app/web/app.py#L1818) |
| GET | `/api/system/feedback-export` | `feedback_export` | [app/web/app.py:1858](../app/web/app.py#L1858) |
| POST | `/api/leads/bulk-action` | `bulk_lead_action` | [app/web/app.py:1870](../app/web/app.py#L1870) |
| POST | `/api/leads/{lead_id}/follow-up` | `schedule_lead_follow_up` | [app/web/app.py:1901](../app/web/app.py#L1901) |
| POST | `/api/leads/{lead_id}/analyze` | `analyze_lead_now` | [app/web/app.py:1931](../app/web/app.py#L1931) |
| POST | `/api/leads/{lead_id}/take` | `take_lead` | [app/web/app.py:1972](../app/web/app.py#L1972) |
| GET | `/api/leads/{lead_id}/explain` | `lead_explain_api` | [app/web/app.py:1985](../app/web/app.py#L1985) |
| POST | `/api/leads/{lead_id}/assign` | `assign_lead` | [app/web/app.py:1993](../app/web/app.py#L1993) |
| POST | `/api/leads/{lead_id}/not-lead` | `not_lead` | [app/web/app.py:2021](../app/web/app.py#L2021) |
| POST | `/api/leads/{lead_id}/stage` | `move_lead` | [app/web/app.py:2034](../app/web/app.py#L2034) |
| POST | `/api/contacts/{contact_id}/notes` | `add_note` | [app/web/app.py:2051](../app/web/app.py#L2051) |
| POST | `/api/contacts/{contact_id}/qualification` | `update_qualification` | [app/web/app.py:2065](../app/web/app.py#L2065) |
| POST | `/api/contacts/{contact_id}/reply` | `customer_reply` | [app/web/app.py:2091](../app/web/app.py#L2091) |
| POST | `/api/contacts/{contact_id}/tasks` | `add_task` | [app/web/app.py:2109](../app/web/app.py#L2109) |
| GET | `/api/audiences/export-recipes` | `list_export_recipes` | [app/web/app.py:2139](../app/web/app.py#L2139) |
| POST | `/api/audiences/export-recipes/{recipe_slug}` | `run_export_recipe_endpoint` | [app/web/app.py:2156](../app/web/app.py#L2156) |
| GET | `/api/openings` | `list_openings_review_queue` | [app/web/app.py:2171](../app/web/app.py#L2171) |
| POST | `/api/openings/{opening_id}/review` | `review_opening_endpoint` | [app/web/app.py:2195](../app/web/app.py#L2195) |
| POST | `/api/agent/query` | `agent_query_endpoint` | [app/web/app.py:2212](../app/web/app.py#L2212) |
| GET | `/agent` | `agent_workspace` | [app/web/app.py:2274](../app/web/app.py#L2274) |
| GET | `/api/agent/sessions` | `agent_sessions_list` | [app/web/app.py:2297](../app/web/app.py#L2297) |
| POST | `/api/agent/sessions` | `agent_sessions_create` | [app/web/app.py:2316](../app/web/app.py#L2316) |
| GET | `/api/agent/sessions/{session_id}/messages` | `agent_session_messages` | [app/web/app.py:2328](../app/web/app.py#L2328) |
| POST | `/api/agent/chat` | `agent_chat_turn` | [app/web/app.py:2352](../app/web/app.py#L2352) |
| POST | `/api/agent/approve` | `agent_approve_action` | [app/web/app.py:2388](../app/web/app.py#L2388) |
| POST | `/api/tasks/{task_id}/complete` | `complete_task` | [app/web/app.py:2407](../app/web/app.py#L2407) |
| POST | `/api/tasks/{task_id}/cancel` | `cancel_task` | [app/web/app.py:2415](../app/web/app.py#L2415) |
| POST | `/api/leads/{lead_id}/reopen` | `reopen_lead` | [app/web/app.py:2423](../app/web/app.py#L2423) |
| POST | `/api/leads/{lead_id}/deal` | `create_or_update_deal` | [app/web/app.py:2435](../app/web/app.py#L2435) |
| POST | `/api/deals/{deal_id}/win` | `win_deal` | [app/web/app.py:2454](../app/web/app.py#L2454) |
| POST | `/api/deals/{deal_id}/lose` | `lose_deal` | [app/web/app.py:2476](../app/web/app.py#L2476) |
| POST | `/api/competitors/import` | `import_competitors_csv` | [app/web/app.py:2494](../app/web/app.py#L2494) |
| POST | `/api/competitors` | `add_competitor` | [app/web/app.py:2512](../app/web/app.py#L2512) |
| POST | `/api/market-catalog/sync` | `sync_market_catalog` | [app/web/app.py:2532](../app/web/app.py#L2532) |
| POST | `/api/competitors/portfolio/activate` | `activate_source_portfolio` | [app/web/app.py:2544](../app/web/app.py#L2544) |
| POST | `/api/market-candidates/{candidate_id}/promote` | `promote_market_candidate` | [app/web/app.py:2585](../app/web/app.py#L2585) |
| POST | `/api/discovery/import` | `import_discovery_file` | [app/web/app.py:2608](../app/web/app.py#L2608) |
| POST | `/api/discovery/candidates/{candidate_id}/status` | `update_discovery_candidate` | [app/web/app.py:2623](../app/web/app.py#L2623) |
| POST | `/api/discovery/diffs/{diff_id}/acknowledge` | `acknowledge_discovery_diff` | [app/web/app.py:2638](../app/web/app.py#L2638) |
| POST | `/api/catalog/import` | `import_catalog` | [app/web/app.py:2646](../app/web/app.py#L2646) |
| POST | `/api/catalog/{product_id}` | `update_catalog_product` | [app/web/app.py:2663](../app/web/app.py#L2663) |
| POST | `/api/competitors/bulk-active` | `bulk_competitors_active` | [app/web/app.py:2688](../app/web/app.py#L2688) |
| POST | `/api/competitors/{competitor_id}/settings` | `update_competitor` | [app/web/app.py:2717](../app/web/app.py#L2717) |
| GET | `/api/radar/feed` | `radar_feed_api` | [app/web/app.py:2756](../app/web/app.py#L2756) |
| GET | `/api/scan/progress` | `scan_progress_api` | [app/web/app.py:2789](../app/web/app.py#L2789) |
| GET | `/health` | `health` | [app/web/app.py:2826](../app/web/app.py#L2826) |
| GET | `/ready` | `ready` | [app/web/app.py:2846](../app/web/app.py#L2846) |
