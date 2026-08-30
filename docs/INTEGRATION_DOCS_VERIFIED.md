# Lead Radar V6 — historical integration research

Этот файл фиксирует ранее изученные направления, но не доказывает текущее подключение,
совместимость версий API или production readiness. Перед реализацией каждой интеграции
официальная документация должна проверяться повторно, а результат — покрываться контрактными
тестами. Сейчас Agent/MCP, Meta и Google остаются `NOT_CONNECTED`.

## Previously reviewed documentation sources

### 1. OpenAI Agents SDK & MCP
- Agents SDK Python docs: `https://openai.github.io/openai-agents-python/`.
- MCP gateway tool schemas и Human-in-the-Loop approval patterns.

### 2. Telegram Mini Apps & Bot API
- Verified WebApp `initData` HMAC-SHA256 signature validation & viewport safe areas.

### 3. Meta Marketing API
- Verified Custom Audience terms & targeting search APIs (`adinterest`).

### 4. Google Places API (New)
- Verified place opening status reporting & cache duration terms.
