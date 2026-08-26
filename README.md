# Lead Radar

Lead Radar — локальный бот для мебельной компании. Он проверяет публичные комментарии под Reels
конкурентов, сначала сохраняет данные в собственной базе, оценивает коммерческий интерес через
OpenAI и отправляет HOT-лиды менеджерам в Telegram.

Первый конкурент по умолчанию: `aiko.uz`. Для безопасной проверки без Instagram API включён mock
provider.

## Что уже работает

- SQLite как source of truth с готовыми Alembic-миграциями;
- единая карточка Contact и полная immutable-история событий;
- дедупликация одного Instagram comment между разными providers;
- baseline без шквала старых Telegram-уведомлений;
- ScrapeCreators с автоматическим fallback на Bright Data;
- OpenAI Structured Outputs с русским и узбекским контекстом;
- `AI_PENDING` и повторный анализ после восстановления OpenAI;
- Telegram `/start`, `/status`, `/stats`, `/hot`, `/competitors`;
- HOT notification, «Взять лид», «Не лид», WON/LOST сделки и AI feedback.

## Требования

- Python 3.12 или новее;
- Telegram bot token для обычного запуска;
- OpenAI API key для AI-оценки;
- ScrapeCreators/Bright Data keys нужны только для реального Instagram, не для mock mode.

Секреты хранятся только в локальном `.env`, который исключён из Git.

## Запуск на Windows

Откройте PowerShell в папке проекта и выполните:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m alembic upgrade head
python -m scripts.check_integrations
python -m app.main
```

Если PowerShell запрещает активацию, можно один раз выполнить для текущего окна:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

## Запуск на macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m alembic upgrade head
python -m scripts.check_integrations
python -m app.main
```

Официальная команда запуска приложения одна:

```bash
python -m app.main
```

## Настройка `.env`

Откройте созданный `.env` и заполните самостоятельно:

```dotenv
TELEGRAM_BOT_TOKEN=...
OPENAI_API_KEY=...
```

Первый запуск можно оставить с `INSTAGRAM_PROVIDER=mock`. Команда `/start` доступна без allowlist
и показывает Telegram Chat ID и User ID. Добавьте нужные значения через запятую:

```dotenv
TELEGRAM_ADMIN_CHAT_IDS=123456789,-1001234567890
```

После изменения `.env` перезапустите приложение. Остальные рабочие команды доступны только этим
ID.

Для реального Instagram:

```dotenv
INSTAGRAM_PROVIDER=scrapecreators
SCRAPECREATORS_API_KEY=...
BRIGHTDATA_API_KEY=...
```

При ошибке, timeout, rate limit или некорректном ответе ScrapeCreators автоматически используется
Bright Data. Можно выбрать только Bright Data: `INSTAGRAM_PROVIDER=brightdata`.

## Baseline и mock demo

Значение по умолчанию `PROCESS_EXISTING_COMMENTS=false` сохраняет уже существующие comments как
baseline и не отправляет по ним уведомления. Все comments после baseline обрабатываются обычно.

Чтобы на совершенно новой тестовой базе сразу прогнать встроенный mock HOT-сценарий, перед первым
запуском временно установите:

```dotenv
INSTAGRAM_PROVIDER=mock
PROCESS_EXISTING_COMMENTS=true
```

Верните `false` перед переходом к реальному конкуренту.

Диагностический одиночный polling cycle без запуска Telegram:

```bash
python -m app.main --once
```

## Проверка интеграций

```bash
python -m scripts.check_integrations
```

Проверяются Database, Telegram, OpenAI, ScrapeCreators и Bright Data. Пустые необязательные ключи
показываются как `SKIP`; значения secrets никогда не печатаются. Проверка реальных Instagram
providers может расходовать один API credit на публичный профиль.

## Тесты и lint

```bash
python -m pytest
ruff check .
```

Внешние API в тестах замоканы; реальные secrets не нужны.

## Переход на PostgreSQL / Railway позже

Railway сейчас не развёртывается. `Dockerfile` и `railway.json` только готовят будущий этап. Для
PostgreSQL достаточно поменять `DATABASE_URL`; сервис автоматически нормализует Railway URL для
`asyncpg`, бизнес-логику переписывать не нужно.

## Текущие ограничения

- реальные API требуют локальной проверки с вашими keys и тарифами;
- Bright Data Comments by URL возвращает последние 15 comments за один synchronous request;
- один локальный процесс и in-memory Telegram FSM; Redis/Celery намеренно отсутствуют;
- отдельного фонового retry worker для FAILED Telegram notifications пока нет, но лид остаётся в
  БД и виден через `/hot`;
- SQLite рассчитан на локальный MVP, не на несколько одновременно запущенных экземпляров.

Подробности устройства: [ARCHITECTURE.md](ARCHITECTURE.md). Реальное состояние работ:
[PROJECT_STATUS.md](PROJECT_STATUS.md).

