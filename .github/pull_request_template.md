## Summary

<!-- 1–3 пункта: что изменилось и зачем -->

## Test plan

- [ ] `python -m ruff check .`
- [ ] `python -m pytest -q`
- [ ] `python -m scripts.check_data_integrity` (если затронута БД/миграции)

## Quality gates (обязательны)

CI job **`offline-quality-gate`** должен быть зелёным до merge:

- `ruff check .`
- `compileall app alembic tests`
- `alembic upgrade head` ×2 + `alembic check`
- `pytest -q` (SQLite и PostgreSQL matrix)
- `scripts.check_data_integrity`

Подробнее: `docs/CI_QUALITY_GATES.md`.

## Checklist

- [ ] Нет секретов в diff (`.env`, tokens)
- [ ] Поведенческие изменения покрыты тестами
- [ ] `PROJECT_STATUS.md` / `State.md` обновлены при substantial stage

## Bugbot (опционально)

Для нетривиальных PR запустите Cursor Bugbot review локально или в cloud agent:

- Security: секреты, auth bypass, SQL injection
- Idempotency: повторные POST/ingestion
- Regression: lead classification, audience recalc

Укажите в summary, если Bugbot прогонялся и что нашёл.
