"""Local process ownership: no database writes, provider calls, or external traffic."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import main as main_module
from app.services.database_runtime_lock import (
    DatabaseRuntimeLock,
    DatabaseRuntimeOwnershipError,
    sqlite_database_path,
)


def _url(path):
    return f"sqlite+aiosqlite:///{path}"


def test_relative_and_absolute_database_paths_share_ownership(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    relative = _url("./lead.db")
    absolute = _url((tmp_path / "lead.db").as_posix())
    assert sqlite_database_path(relative) == sqlite_database_path(absolute)
    with DatabaseRuntimeLock(relative) as owner:
        assert owner.exclusive
        with pytest.raises(DatabaseRuntimeOwnershipError):
            with DatabaseRuntimeLock(absolute):
                pytest.fail("The same database was opened twice")
    with DatabaseRuntimeLock(absolute) as owner:
        assert owner.exclusive


def test_exception_releases_database_ownership(tmp_path):
    url = _url((tmp_path / "lead.db").as_posix())
    with pytest.raises(RuntimeError, match="stop"):
        with DatabaseRuntimeLock(url):
            raise RuntimeError("stop")
    with DatabaseRuntimeLock(url) as owner:
        assert owner.exclusive


@pytest.mark.parametrize("url", [
    "sqlite+aiosqlite://", "sqlite+aiosqlite:///:memory:",
    "sqlite+aiosqlite:///file:memorydb?mode=memory&cache=shared&uri=true",
    "postgresql+asyncpg://user:secret-in-dsn@localhost/database",
])
def test_non_file_databases_do_not_claim_exclusive_ownership(url):
    with DatabaseRuntimeLock(url) as owner:
        assert owner.database_path is None
        assert not owner.exclusive


def test_file_uri_and_normal_sqlite_path_share_ownership(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    regular = _url("./lead.db")
    uri = _url("file:lead.db?mode=rwc&uri=true")
    assert sqlite_database_path(regular) == sqlite_database_path(uri)
    with DatabaseRuntimeLock(regular):
        with pytest.raises(DatabaseRuntimeOwnershipError):
            with DatabaseRuntimeLock(uri):
                pytest.fail("URI alias bypassed ownership")


def test_second_process_fails_closed_and_crashed_owner_releases_lock(tmp_path):
    project_dir = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(project_dir), "PYTHONIOENCODING": "utf-8"}
    url = _url((tmp_path / "lead.db").as_posix())
    owner_code = (
        "import sys; from app.services.database_runtime_lock import DatabaseRuntimeLock; "
        "lock=DatabaseRuntimeLock(sys.argv[1]); lock.__enter__(); "
        "print('LOCKED',flush=True); sys.stdin.read()"
    )
    contender_code = """
import sys
from app.services.database_runtime_lock import DatabaseRuntimeLock, DatabaseRuntimeOwnershipError
try:
    with DatabaseRuntimeLock(sys.argv[1]) as owner:
        print('ACQUIRED' if owner.exclusive else 'UNPROVEN', flush=True)
except DatabaseRuntimeOwnershipError:
    print('BLOCKED', flush=True)
    sys.exit(23)
"""
    owner = subprocess.Popen(
        [sys.executable, "-c", owner_code, url], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=project_dir, env=env,
    )
    try:
        assert owner.stdout.readline().strip() == "LOCKED"
        contender = subprocess.run(
            [sys.executable, "-c", contender_code, url], capture_output=True,
            text=True, cwd=project_dir, env=env, timeout=15,
        )
        assert contender.returncode == 23
        assert contender.stdout.strip() == "BLOCKED"
        owner.kill()
        owner.wait(timeout=10)
        replacement = subprocess.run(
            [sys.executable, "-c", contender_code, url], capture_output=True,
            text=True, cwd=project_dir, env=env, timeout=15,
        )
        assert replacement.returncode == 0
        assert replacement.stdout.strip() == "ACQUIRED"
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)


async def test_main_rejects_second_instance_before_any_startup_work(tmp_path, monkeypatch):
    url = _url((tmp_path / "lead.db").as_posix())
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(database_url=url))
    owned_body = AsyncMock(return_value=0)
    backup = Mock()
    upgrade = AsyncMock()
    monkeypatch.setattr(main_module, "_run_owned", owned_body)
    monkeypatch.setattr(main_module, "backup_sqlite_database", backup)
    monkeypatch.setattr(main_module, "upgrade_database", upgrade)
    with DatabaseRuntimeLock(url):
        with pytest.raises(DatabaseRuntimeOwnershipError):
            await main_module.run(once=True)
    owned_body.assert_not_called()
    backup.assert_not_called()
    upgrade.assert_not_called()


async def test_main_holds_lock_until_owned_runtime_finishes_and_then_releases(tmp_path, monkeypatch):
    url = _url((tmp_path / "lead.db").as_posix())
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(database_url=url))
    started = asyncio.Event()
    release = asyncio.Event()

    async def owned_body(settings, **kwargs):
        assert kwargs["exclusive_runtime"]
        started.set()
        await release.wait()
        return 7

    monkeypatch.setattr(main_module, "_run_owned", owned_body)
    task = asyncio.create_task(main_module.run(web_only=True))
    await started.wait()
    with pytest.raises(DatabaseRuntimeOwnershipError):
        with DatabaseRuntimeLock(url):
            pytest.fail("Runtime ownership ended before the server stopped")
    release.set()
    assert await task == 7
    with DatabaseRuntimeLock(url) as owner:
        assert owner.exclusive


async def test_postgres_startup_does_not_claim_recovery_ownership(monkeypatch):
    url = "postgresql+asyncpg://user:secret-in-dsn@localhost/database"
    monkeypatch.setattr(main_module, "get_settings", lambda: SimpleNamespace(database_url=url))
    owned_body = AsyncMock(return_value=0)
    monkeypatch.setattr(main_module, "_run_owned", owned_body)
    assert await main_module.run() == 0
    assert owned_body.call_args.kwargs["exclusive_runtime"] is False


def test_configuration_error_never_exposes_connection_details():
    with pytest.raises(DatabaseRuntimeOwnershipError) as failure:
        DatabaseRuntimeLock("secret-in-dsn is not a database URL")
    assert "secret-in-dsn" not in str(failure.value)
