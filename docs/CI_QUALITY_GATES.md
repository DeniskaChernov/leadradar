# CI Quality Gates

Все PR и push в main должны проходить workflow `.github/workflows/ci.yml`.

## Job: `offline-quality-gate`

Matrix: **SQLite** + **PostgreSQL 16**.

| Шаг | Команда | Назначение |
|-----|---------|------------|
| Lint | `python -m ruff check .` | Стиль и статический анализ |
| Compile | `python -m compileall -q app alembic tests` | Синтаксис |
| Migrate | `alembic upgrade head` ×2 | Идемпотентность миграций |
| Drift | `alembic check` | Schema drift |
| Tests | `python -m pytest -q` | Регрессии |
| Integrity | `python -m scripts.check_data_integrity` | Дубликаты и FK |

## Локальная проверка перед PR

```bash
python -m ruff check .
python -m pytest -q
python -m scripts.check_data_integrity
```

## Branch protection (рекомендация)

В GitHub Settings → Branches → `main`:

- Require status check: **`offline-quality-gate (sqlite)`**
- Require status check: **`offline-quality-gate (postgres)`**

Оба matrix-варианта должны быть required — иначе merge возможен при падении одной БД.

## Переменные CI

```env
EXTERNAL_KILL_SWITCH=true
OPENAI_LIVE_CALLS_ENABLED=false
INSTAGRAM_LIVE_CALLS_ENABLED=false
LEAD_SEARCH_ENABLED=false
MONITOR_SCHEDULE_ENABLED=false
```

Live-вызовы в CI запрещены — только offline/replay.
