"""Process ownership for file-backed SQLite before any startup database work."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlparse

from sqlalchemy.engine import make_url


class DatabaseRuntimeOwnershipError(RuntimeError):
    """Startup cannot establish exclusive ownership of a local SQLite database."""


def sqlite_database_path(database_url: str) -> Path | None:
    """Resolve aliases of the same SQLite file to the same operating-system lock."""
    try:
        url = make_url(database_url)
    except Exception:
        raise DatabaseRuntimeOwnershipError("Некорректная настройка базы данных.") from None
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:" or url.query.get("mode") == "memory":
        return None
    if url.query.get("uri", "").lower() == "true" and database.startswith("file:"):
        file_url = urlparse(database)
        if file_url.netloc not in {"", "localhost"}:
            raise DatabaseRuntimeOwnershipError("Неподдерживаемый адрес локальной базы SQLite.")
        database = unquote(file_url.path)
        if os.name == "nt" and len(database) > 2 and database[0] == "/" and database[2] == ":":
            database = database[1:]
        if database == ":memory:":
            return None
    return Path(database).resolve()


class DatabaseRuntimeLock:
    """Hold an OS file lock for the lifetime of one application process.

    Closing the file, including process termination, releases ownership. The
    lock file remains in place so a new process cannot race on a replaced inode.
    PostgreSQL and memory-only databases provide no exclusive ownership here.
    """

    def __init__(self, database_url: str) -> None:
        self.database_path = sqlite_database_path(database_url)
        self.exclusive = False
        self._file: BinaryIO | None = None

    def __enter__(self) -> DatabaseRuntimeLock:
        if self._file is not None:
            raise DatabaseRuntimeOwnershipError("Блокировка процесса уже получена.")
        if self.database_path is None:
            return self
        try:
            lock_dir = self.database_path.parent / ".runtime"
            lock_dir.mkdir(parents=True, exist_ok=True)
            self._file = (lock_dir / f"{self.database_path.name}.instance.lock").open("a+b")
            self._file.seek(0, os.SEEK_END)
            if self._file.tell() == 0:
                self._file.write(b"\0")
                self._file.flush()
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self._file is not None:
                self._file.close()
                self._file = None
            raise DatabaseRuntimeOwnershipError(
                "Lead Radar уже использует эту базу SQLite или блокировка недоступна. "
                "Второй процесс не запущен."
            ) from None
        self.exclusive = True
        return self

    def __exit__(self, *_args: object) -> None:
        if self._file is None:
            return
        try:
            with contextlib.suppress(OSError):
                self._file.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None
            self.exclusive = False
