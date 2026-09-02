# Lead Radar — Database Backup & Restore Runbook

## 1. Automated Backups
Lead Radar automatically backs up the SQLite database before app startup or database migrations when `DATABASE_BACKUP_ON_START=true` (default).

Backups are stored in `.backups/` with filenames formatted as:
`lead_radar_YYYYMMDD_HHMMSS.db`

The system automatically maintains the last N backups (configurable via `DATABASE_BACKUP_KEEP=10`).

## 2. Manual Backup Creation
To create a manual backup at any time:
```bash
python scripts/backup_database.py
```

## 3. Database Restoration
To restore from the most recent backup:
```bash
python scripts/restore_database.py
```

To restore from a specific backup file:
```bash
python scripts/restore_database.py .backups/lead_radar_20260827_120000.db
```

To bypass confirmation in automated recovery scripts:
```bash
python scripts/restore_database.py .backups/lead_radar_20260827_120000.db --force
```

## 4. Post-Restore Verification
Always run integrity checks after restoring:
```bash
$env:PYTHONPATH="."
python scripts/check_data_integrity.py
python -m pytest -q
```

## 5. Restore Drill (ежеквартально)

Цель: убедиться, что backup реально восстанавливается, а не только создаётся.

### Шаги (staging / локальная копия prod)

1. Зафиксировать текущее состояние: `python scripts/check_data_integrity.py` → OK.
2. Создать manual backup: `python scripts/backup_database.py`.
3. Внести контрольное изменение (например, создать тестового конкурента на паузе).
4. Восстановить backup: `python scripts/restore_database.py .backups/<latest>.db --force`.
5. Проверить, что контрольное изменение исчезло.
6. Прогнать `check_data_integrity` + `pytest -q`.
7. Записать результат в `State.md`: `backup-drill: OK|FAIL YYYY-MM-DD`.

### PostgreSQL

Managed PG: drill через snapshot/PITR провайдера (Railway/Neon). SQLite runbook выше —
только для локального/staging SQLite.

### Критерий успеха

- Restore завершился без ошибок.
- Integrity scan → 0 duplicates.
- `GET /ready` → 200 после перезапуска web.
