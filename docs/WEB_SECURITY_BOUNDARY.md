# Web security boundary

## Режимы запуска

Локальный режим разрешён только на loopback host (`127.0.0.1`, `localhost`, `::1`) и может
работать с `WEB_AUTH_ENABLED=false`. В этом режиме действия выполняются от локального
администратора из `WEB_MANAGER_ID` или первого admin ID.

Любой публичный `WEB_HOST` или `WEB_PUBLIC_URL` требует одновременно:

- `WEB_AUTH_ENABLED=true`;
- HTTPS в `WEB_PUBLIC_URL`;
- `TELEGRAM_BOT_TOKEN`;
- хотя бы один разрешённый Telegram user ID.

Некорректная комбинация отклоняется при чтении конфигурации до запуска приложения.

## Роли

Каждый Telegram ID принадлежит ровно одному списку:

- `TELEGRAM_VIEWER_CHAT_IDS` — read-only страницы и GET API;
- `TELEGRAM_MANAGER_CHAT_IDS` — CRM, задачи, сделки и модерация;
- `TELEGRAM_ADMIN_CHAT_IDS` — системные настройки, scan/replay, imports, catalog,
  competitors, pricing и будущий Agent gateway.

Пересечение списков запрещено. Роль вычисляется при каждом запросе, поэтому удаление ID
из allowlist немедленно отзывает существующую сессию.

## Сессия и запросы

- Telegram `initData` проверяется HMAC-SHA256 и принимается не старше 300 секунд по умолчанию.
- Сессионная cookie подписана ключом, производным от bot token, имеет `HttpOnly`,
  `SameSite=Strict` и `Secure` на HTTPS.
- POST/PUT/PATCH/DELETE требуют связанный с сессией `X-CSRF-Token`.
- Публичная auth-конфигурация ограничивает допустимый Host.
- Динамические ответы имеют `Cache-Control: no-store`, CSP, nosniff, referrer и permissions
  headers; HTTPS получает HSTS.

Telegram bot permissions остаются отдельным контуром и не расширяются web-ролью.
