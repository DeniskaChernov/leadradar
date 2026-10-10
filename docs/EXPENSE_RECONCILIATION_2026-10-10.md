# Сверка расхода №235 — 2026-10-10

Резервация Instagram №235 окончательно сверена по журналу ScrapeCreators.
Запрос `/v2/instagram/post/comments` по публикации `DdtTeCFoJe-`
компании sellamenza.uz начат провайдером 09.10 в 15:57:22,023 Ташкент
(10:57:22,023 UTC), завершился HTTP 500. Журнал содержит `credits=1`.
Момент отправки в локальной БД — 15:57:21,908; найден ровно один запрос
в интервале ±1 секунды. Публикация подтверждена в БД: post 36, sellamenza.uz.

Через ExternalUsageService.finalize_reservation сохранены исходная причина,
подтверждение провайдера и SHA256 локального файла доказательств.
Статус FINALIZED, actual_units=1, unit_source=PROVIDER_CONFIRMED.
Успех получения комментариев остаётся false: подтверждение оплаты не означает
успешную загрузку. CostEvent для №235 ровно один; ExternalUsage создан однократно.

Для сверки выполнены два запроса account/get-api-usage. Первый ответ был получен,
но ошибка закрытия адаптера (`close` вместо `aclose`) прервала сохранение
доказательства; понадобился второй запрос. Оба учтены отдельно:
резервации 239/240, FINALIZED, по 1 credit, ESTIMATED согласно опубликованному
тарифу. Фактическое списание за эти диагностические запросы отдельно не
подтверждено журналом: запросы фильтровались по endpoint комментариев.
Второй журнал и результат сверки сохранены в игнорируемом `.runtime`.
Аккаунт провайдера не пополнялся; повторный запрос комментариев не выполнялся.

Итог месяца ScrapeCreators: 51 подтверждённый Instagram credit + 2 оценочных
account credits = 53; hard limit 3800, remaining 3747. Это внутренний месячный
бюджет, а не свежий баланс кошелька провайдера. Старый wallet snapshot 31273
не обновлялся и не выдаётся за актуальный.

Неопределённых Instagram-запросов: 0. Preview FURNITURE/max_credits=5:
локально и через действующий Cloudflare can_start=true, effective=5,
blocking_reasons=[]; /ready=200. Браузер показывает активную кнопку ручного
поиска. Поиск, GPT и Telegram-отправки при сверке не запускались.

Резервная копия БД создана до расходов сверки, integrity ok; текущая БД:
integrity ok, FK 0. Хеши 10 контрольных таблиц совпали с предыдущим этапом:
comments/posts/leads/contacts/contact_events/notification_logs/
significant_change_notifications/ai_requests/monitor_runs/provider_credit_snapshots.
287 комментариев/лидов, 259 контактов, 864 contact_events, 95 SENT сохранены.
ExternalUsage/CostEvent/ExternalBudgetReservation теперь по 240 строк.

Проверки: pytest test_budget_reservation.py + test_search_preparation.py:
58 passed; test_provider_credit_budget.py: 4 passed. Ruff check . PASS.
Полный pytest проекта не повторялся. Код продукта и runtime не изменены,
предыдущие ограничения качества и полноты сбора не считаются устранёнными.

Источник тарифа и формата журнала:
https://docs.scrapecreators.com/v1/account/get-api-usage/
