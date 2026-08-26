from __future__ import annotations

from app.config import get_settings
from app.db.session import backup_sqlite_database


def main() -> None:
    destination = backup_sqlite_database(get_settings())
    if destination is None:
        print("Backup: not required (database missing, disabled, or not SQLite).")
    else:
        print(f"Backup created: {destination}")


if __name__ == "__main__":
    main()
