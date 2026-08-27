"""
restore_database.py — Safety script to restore Lead Radar SQLite database from a backup.

Usage:
  python scripts/restore_database.py [.backups/backup_filename.db] [--force]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from app.config import get_settings


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

    # Determine target database path
    raw_url = settings.database_url
    if "///" in raw_url:
        db_path = Path(raw_url.split("///")[1]).resolve()
    else:
        print(f"Error: Database URL is not a local SQLite file: {raw_url}")
        sys.exit(1)

    # Determine backup path
    if args.backup_path:
        source_file = Path(args.backup_path).resolve()
    else:
        backups_dir = Path(".backups").resolve()
        if not backups_dir.exists():
            print("Error: .backups/ directory does not exist.")
            sys.exit(1)
        backup_files = sorted(backups_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not backup_files:
            print("Error: No backup .db files found in .backups/")
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

    # Perform atomic restore
    shutil.copy2(source_file, db_path)
    print(f"Database successfully restored from {source_file.name} to {db_path.name}")


if __name__ == "__main__":
    main()
