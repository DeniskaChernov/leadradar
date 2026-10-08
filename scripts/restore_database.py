"""
restore_database.py — Safety script to restore Lead Radar SQLite database from a backup.

Usage:
  python scripts/restore_database.py [.backups/backup_filename.db] [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.services.database_backup_service import DatabaseBackupError, restore_sqlite_database
from app.services.database_runtime_lock import DatabaseRuntimeOwnershipError, sqlite_database_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore Lead Radar SQLite database from backup.")
    parser.add_argument(
        "backup_path",
        nargs="?",
        help="Path to the backup file. Defaults to the latest file in .backups/",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass interactive confirmation prompt.",
    )
    args = parser.parse_args()

    settings = get_settings()

    try:
        db_path = sqlite_database_path(settings.database_url)
    except DatabaseRuntimeOwnershipError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    if db_path is None:
        print("Error: Restore requires a file-backed SQLite database.")
        sys.exit(1)

    # Determine backup path
    if args.backup_path:
        source_file = Path(args.backup_path).resolve()
    else:
        backups_dir = db_path.parent / ".backups"
        if not backups_dir.exists():
            print("Error: .backups/ directory does not exist.")
            sys.exit(1)
        backup_files = sorted(
            backups_dir.glob(f"{db_path.stem}-*{db_path.suffix or '.db'}"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not backup_files:
            print("Error: No backups matching the configured database were found.")
            sys.exit(1)
        source_file = backup_files[0]

    if not source_file.exists():
        print(f"Error: Backup file not found: {source_file}")
        sys.exit(1)

    print(f"Restore Source: {source_file}")
    print(f"Restore Target: {db_path}")

    if not args.force:
        confirm = input("WARNING: Overwriting current database! Type 'YES' to proceed: ")
        if confirm.strip() != "YES":
            print("Restore cancelled.")
            sys.exit(0)

    try:
        result = restore_sqlite_database(settings.database_url, source_file)
    except (DatabaseBackupError, DatabaseRuntimeOwnershipError) as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    if result.recovery_copy is not None:
        print(f"Original file preserved: {result.recovery_copy}")
    print(f"Database successfully restored from {source_file.name} to {db_path.name}")


if __name__ == "__main__":
    main()
