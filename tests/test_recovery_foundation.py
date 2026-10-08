"""Recovery checks use disposable SQLite files and never change the live database."""

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main as main_module
from app.db.session import backup_sqlite_database
from app.main import configure_logging
from app.services.database_backup_service import (
    DatabaseBackupError,
    create_sqlite_snapshot,
    restore_sqlite_database,
)
from app.services.database_runtime_lock import DatabaseRuntimeLock
from app.services.runtime_diagnostics_service import RuntimeDiagnostics
from scripts import restore_database


def _settings(path, **overrides):
    return SimpleNamespace(
        database_url=f"sqlite+aiosqlite:///{path.as_posix()}",
        database_backup_on_start=overrides.get("enabled", True),
        database_backup_keep=overrides.get("keep", 10),
    )


def _database(path, value):
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE probe(value TEXT)")
        connection.execute("INSERT INTO probe VALUES (?)", (value,))
        connection.commit()


def _value(path):
    with contextlib.closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT value FROM probe").fetchone()[0]


@pytest.mark.parametrize("attached", [False, True])
async def test_real_asgi_lifespan_marks_attached_runtime_ready(session_factory, tmp_path, attached):
    from tests.test_qa_smoke_pages import _app

    app = _app(session_factory)
    diagnostics = RuntimeDiagnostics(_settings(tmp_path / "lead.db").database_url, "web-only")
    diagnostics.start()
    if attached:
        app.state.runtime_diagnostics = diagnostics
    async with app.router.lifespan_context(app):
        assert diagnostics.snapshot()["phase"] == ("SERVING" if attached else "STARTUP")
    # The main runtime owns the terminal receipt, not ASGI shutdown alone.
    assert diagnostics.snapshot()["state"] == "RUNNING"


async def test_web_only_entrypoint_uses_real_fastapi_lifespan(
    file_session_factory, tmp_path, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    from app.config import Settings

    engine = file_session_factory.kw["bind"]
    settings = Settings(
        _env_file=None,
        database_url=str(engine.url),
        database_backup_on_start=False,
        web_enabled=True,
        web_auth_enabled=False,
        lead_search_enabled=False,
        instagram_provider="replay",
        openai_api_key="",
        telegram_bot_token="",
        sentry_dsn="",
        meta_ads_live_enabled=False,
    )

    async def no_migration():
        pass

    async def close_provider():
        pass

    provider = SimpleNamespace(name="replay", safe_mode=True, aclose=close_provider)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "upgrade_database", no_migration)
    monkeypatch.setattr(main_module, "create_engine", lambda _settings: engine)
    monkeypatch.setattr(main_module, "create_instagram_provider", lambda *args, **kwargs: provider)
    served = []

    async def serve(server, shutdown_event):
        app = server.config.app
        diagnostics = app.state.runtime_diagnostics
        assert diagnostics.snapshot()["phase"] == "STARTUP"
        async with app.router.lifespan_context(app):
            assert diagnostics.snapshot()["phase"] == "SERVING"
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                health = await client.get("/health")
                assert health.status_code == 200 and health.json()["ok"]
                system = await client.get("/system")
                assert system.status_code == 200 and "Работа сервера" in system.text
            served.append(diagnostics)
        shutdown_event.set()

    monkeypatch.setattr(main_module, "_serve_web_until_shutdown", serve)
    assert await asyncio.wait_for(main_module.run(web_only=True), timeout=30) == 0
    assert len(served) == 1
    assert served[0].snapshot()["state"] == "STOPPED"
    assert served[0].snapshot()["reason"] == "completed"


def test_online_backup_includes_committed_wal(tmp_path):
    source = tmp_path / "wal.db"
    connection = sqlite3.connect(source)
    try:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE probe(value TEXT)")
        connection.execute("INSERT INTO probe VALUES ('committed-in-wal')")
        connection.commit()
        assert source.with_name(source.name + "-wal").stat().st_size > 0
        backup = backup_sqlite_database(_settings(source))
        assert _value(backup) == "committed-in-wal"
    finally:
        connection.close()


def test_restore_cli_cannot_replace_database_owned_by_server(tmp_path, monkeypatch):
    source = tmp_path / "backup.db"
    target = tmp_path / "live.db"
    _database(source, "backup")
    _database(target, "live")
    settings = _settings(target)
    monkeypatch.setattr(restore_database, "get_settings", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["restore", str(source), "--force"])
    with DatabaseRuntimeLock(settings.database_url):
        with pytest.raises((SystemExit, RuntimeError)):
            restore_database.main()
        assert _value(target) == "live"


@pytest.mark.parametrize("message", ['quoted "value"', "line1\nline2", r"C:\path\file", "текст"])
def test_json_logging_messages_are_real_single_line_json(monkeypatch, message):
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    monkeypatch.setenv("LOG_FORMAT", "json")
    try:
        configure_logging(SimpleNamespace(log_level="INFO"))
        record = logging.LogRecord("probe", logging.INFO, "", 1, message, (), None)
        output = root.handlers[0].formatter.format(record)
        assert len(output.splitlines()) == 1
        assert json.loads(output)["message"] == message
    finally:
        root.handlers = handlers
        root.setLevel(level)


def _radar_database(path, value):
    _database(path, value)
    with contextlib.closing(sqlite3.connect(path)) as db:
        db.executescript("""
            CREATE TABLE alembic_version(version_num TEXT);
            INSERT INTO alembic_version VALUES ('a7c8d9e0f1b2');
            CREATE TABLE contacts(id INTEGER PRIMARY KEY);
            CREATE TABLE comments(id INTEGER PRIMARY KEY, contact_id INTEGER REFERENCES contacts(id));
            CREATE TABLE leads(id INTEGER PRIMARY KEY, comment_id INTEGER REFERENCES comments(id));
            CREATE TABLE contact_events(id INTEGER PRIMARY KEY, contact_id INTEGER REFERENCES contacts(id), text TEXT);
            CREATE TABLE cost_events(id INTEGER PRIMARY KEY);
            CREATE TABLE external_usage(id INTEGER PRIMARY KEY);
            INSERT INTO contacts VALUES (1);
            INSERT INTO comments VALUES (1, 1);
            INSERT INTO leads VALUES (1, 1);
            INSERT INTO contact_events VALUES (1, 1, 'immutable-history');
        """)


def test_backup_excludes_uncommitted_wal_and_is_standalone(tmp_path):
    source = tmp_path / "pending.db"
    _database(source, "committed")
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("UPDATE probe SET value='uncommitted'")
        backup = backup_sqlite_database(_settings(source))
        assert _value(backup) == "committed"
        with contextlib.closing(sqlite3.connect(backup)) as db:
            assert db.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert not list(backup.parent.glob("*-wal"))
        assert not list(backup.parent.glob("*-shm"))
    finally:
        connection.close()


def test_manual_backup_works_when_startup_backup_disabled(tmp_path):
    source = tmp_path / "manual.db"
    _database(source, "manual")
    settings = _settings(source, enabled=False)
    assert backup_sqlite_database(settings) is None
    assert _value(backup_sqlite_database(settings, manual=True)) == "manual"


@pytest.mark.parametrize("uri", [False, True])
def test_backup_handles_file_alias_and_sqlite_options(tmp_path, monkeypatch, uri):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "a #b.db"
    _database(source, "alias")
    settings = _settings(source)
    settings.database_url = (
        f"sqlite+aiosqlite:///{source.as_uri()}?mode=ro&uri=true"
        if uri
        else "sqlite+aiosqlite:///./a #b.db?timeout=3"
    )
    assert _value(backup_sqlite_database(settings)) == "alias"


def test_backup_retention_keeps_latest_success_and_does_not_touch_other_database(tmp_path):
    source = tmp_path / "lead.db"
    _database(source, "first")
    old = backup_sqlite_database(_settings(source))
    other = old.parent / "other-20000101.db"
    other.write_bytes(b"other")
    newest = backup_sqlite_database(_settings(source, keep=1))
    assert newest.exists()
    assert not old.exists()
    assert other.read_bytes() == b"other"


def test_failed_backup_does_not_publish_or_prune_previous_copy(tmp_path):
    source = tmp_path / "lead.db"
    _database(source, "valid")
    backup = backup_sqlite_database(_settings(source, keep=1))
    source.write_bytes(b"damaged")
    with pytest.raises(DatabaseBackupError):
        backup_sqlite_database(_settings(source, keep=1))
    assert _value(backup) == "valid"
    assert list(backup.parent.iterdir()) == [backup]


def test_snapshot_timeout_preserves_destination(tmp_path):
    source, destination = tmp_path / "source.db", tmp_path / "existing.db"
    _database(source, "source")
    _database(destination, "destination")
    with pytest.raises(DatabaseBackupError):
        create_sqlite_snapshot(source, destination, timeout_seconds=-1)
    assert _value(destination) == "destination"
    assert not list(tmp_path.glob(".sqlite-snapshot-*"))


@pytest.mark.parametrize("same", ["path", "hardlink"])
def test_snapshot_cannot_replace_its_source(tmp_path, same):
    source = tmp_path / "source.db"
    _database(source, "original")
    destination = source if same == "path" else tmp_path / "alias.db"
    if same == "hardlink":
        destination.hardlink_to(source)
    with pytest.raises(DatabaseBackupError):
        create_sqlite_snapshot(source, destination)
    assert _value(source) == "original"


def test_restore_preserves_old_file_and_all_snapshot_history(tmp_path):
    source, target = tmp_path / "backup.db", tmp_path / "live.db"
    _radar_database(source, "snapshot")
    _radar_database(target, "newer")
    original = target.read_bytes()
    result = restore_sqlite_database(_settings(target).database_url, source)
    assert _value(target) == "snapshot"
    assert result.recovery_copy.read_bytes() == original
    with contextlib.closing(sqlite3.connect(target)) as db:
        assert db.execute("SELECT text FROM contact_events").fetchall() == [("immutable-history",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    restore_sqlite_database(_settings(target).database_url, source)
    with contextlib.closing(sqlite3.connect(target)) as db:
        assert db.execute("SELECT count(*) FROM contact_events").fetchone()[0] == 1
    assert not list(tmp_path.glob(".sqlite-*-*"))


@pytest.mark.parametrize(
    "invalid", ["corrupt", "wrong_app", "foreign_key", "revision", "revision_alias"]
)
def test_restore_rejects_invalid_copy_without_touching_target(tmp_path, invalid):
    source, target = tmp_path / "backup.db", tmp_path / "live.db"
    _radar_database(target, "live")
    if invalid == "corrupt":
        source.write_bytes(b"damaged")
    elif invalid == "wrong_app":
        _database(source, "unrelated")
    else:
        _radar_database(source, "invalid")
        with contextlib.closing(sqlite3.connect(source)) as db:
            if invalid == "foreign_key":
                db.execute("UPDATE comments SET contact_id=999")
            else:
                db.execute(
                    "UPDATE alembic_version SET version_num=?",
                    ("head" if invalid == "revision_alias" else "unrecognized",),
                )
            db.commit()
    original = target.read_bytes()
    with pytest.raises(DatabaseBackupError):
        restore_sqlite_database(_settings(target).database_url, source)
    assert target.read_bytes() == original
    assert not list(tmp_path.glob(".sqlite-*-*"))
    assert not (tmp_path / ".backups").exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_restore_cannot_discard_existing_sidecars(tmp_path, suffix):
    source, target = tmp_path / "backup.db", tmp_path / "live.db"
    _radar_database(source, "source")
    _radar_database(target, "target")
    sidecar = target.with_name(target.name + suffix)
    sidecar.write_bytes(b"uncheckpointed")
    original = target.read_bytes()
    with pytest.raises(DatabaseBackupError):
        restore_sqlite_database(_settings(target).database_url, source)
    assert target.read_bytes() == original
    assert sidecar.read_bytes() == b"uncheckpointed"


def test_restore_can_replace_corrupt_target_and_preserves_for_investigation(tmp_path):
    source, target = tmp_path / "backup.db", tmp_path / "broken.db"
    _radar_database(source, "recovered")
    target.write_bytes(b"damaged-original")
    result = restore_sqlite_database(_settings(target).database_url, source)
    assert result.recovery_copy.read_bytes() == b"damaged-original"
    assert _value(target) == "recovered"


def test_failed_atomic_restore_keeps_original_and_recovery_copy(tmp_path, monkeypatch):
    import app.services.database_backup_service as service

    source, target = tmp_path / "backup.db", tmp_path / "live.db"
    _radar_database(source, "source")
    _radar_database(target, "live")
    original, replace = target.read_bytes(), service.os.replace

    def fail_at_target(old, new):
        if new == target:
            raise PermissionError("simulated")
        return replace(old, new)

    monkeypatch.setattr(service.os, "replace", fail_at_target)
    with pytest.raises(DatabaseBackupError):
        restore_sqlite_database(_settings(target).database_url, source)
    assert target.read_bytes() == original
    assert next((tmp_path / ".backups").glob("*.original")).read_bytes() == original
    assert not list(tmp_path.glob(".sqlite-*-*"))


@pytest.mark.parametrize(
    "url", ["sqlite+aiosqlite:///:memory:", "postgresql://user:secret@host/db"]
)
def test_restore_non_file_database_is_refused_without_connection_details(tmp_path, url):
    with pytest.raises(DatabaseBackupError) as result:
        restore_sqlite_database(url, tmp_path / "source.db")
    assert "secret" not in str(result.value)


def test_lifecycle_receipt_distinguishes_unfinished_previous_process(tmp_path):
    url = _settings(tmp_path / "lead.db").database_url
    first = RuntimeDiagnostics(url, "web-only")
    first.start()
    first.ready()
    second = RuntimeDiagnostics(url, "web-only")
    second.start()
    assert second.snapshot()["previous"]["unfinished"] is True
    assert second.snapshot()["previous"]["reason"] is None
    second.finish(exit_code=0)
    third = RuntimeDiagnostics(url, "web-only")
    third.start()
    assert third.snapshot()["previous"]["state"] == "STOPPED"
    assert third.snapshot()["previous"]["unfinished"] is False
    assert "database_url" not in json.loads(third.path.read_text())


@pytest.mark.parametrize(
    "error,code,state",
    [
        (RuntimeError("secret-token"), None, "FAILED"),
        (asyncio.CancelledError(), None, "INTERRUPTED"),
        (None, 2, "FAILED"),
        (None, 0, "STOPPED"),
    ],
)
def test_lifecycle_terminal_state_does_not_store_exception_text(tmp_path, error, code, state):
    diagnostics = RuntimeDiagnostics(_settings(tmp_path / "lead.db").database_url, "web-only")
    diagnostics.start()
    diagnostics.finish(error=error, exit_code=code)
    receipt = diagnostics.path.read_text()
    assert json.loads(receipt)["state"] == state
    assert json.loads(receipt)["stopped_at"]
    assert "secret-token" not in receipt


@pytest.mark.parametrize(
    "receipt",
    ["not-json", "[]", '{"state":"unexpected"}', "x" * 32769],
    ids=["broken-json", "array", "unknown-state", "oversized"],
)
def test_unreadable_lifecycle_receipt_does_not_prevent_startup(tmp_path, receipt):
    diagnostics = RuntimeDiagnostics(_settings(tmp_path / "lead.db").database_url, "web-only")
    diagnostics.path.parent.mkdir(parents=True)
    diagnostics.path.write_text(receipt)
    diagnostics.start()
    assert diagnostics.snapshot()["previous"]["state"] == "UNREADABLE"
    assert json.loads(diagnostics.path.read_text())["state"] == "RUNNING"


async def test_lifecycle_heartbeat_updates_and_cancels(tmp_path):
    diagnostics = RuntimeDiagnostics(_settings(tmp_path / "lead.db").database_url, "web-only")
    diagnostics.start()
    initial = diagnostics.snapshot()["heartbeat_at"]
    task = asyncio.create_task(diagnostics.heartbeat(interval=0.01))
    try:
        await asyncio.sleep(0.035)
        assert diagnostics.snapshot()["heartbeat_at"] != initial
        assert (
            json.loads(diagnostics.path.read_text())["heartbeat_at"]
            == diagnostics.snapshot()["heartbeat_at"]
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_lifecycle_write_failure_keeps_prior_receipt_and_does_not_stop_service(
    tmp_path, monkeypatch
):
    import app.services.runtime_diagnostics_service as service

    diagnostics = RuntimeDiagnostics(_settings(tmp_path / "lead.db").database_url, "web-only")
    diagnostics.start()
    original = diagnostics.path.read_bytes()
    monkeypatch.setattr(
        service.os, "replace", lambda *args: (_ for _ in ()).throw(PermissionError("denied"))
    )
    diagnostics.ready()
    assert not diagnostics.snapshot()["persisted"]
    assert diagnostics.path.read_bytes() == original
    assert not list(diagnostics.path.parent.glob(".lifecycle-*"))


@pytest.mark.parametrize("url", ["sqlite+aiosqlite://", "postgresql://user:secret@host/db"])
def test_non_file_runtime_has_truthful_in_memory_diagnostics(url):
    diagnostics = RuntimeDiagnostics(url, "web-only")
    diagnostics.start()
    diagnostics.ready()
    assert diagnostics.path is None
    assert not diagnostics.snapshot()["persistent_supported"]
    assert not diagnostics.snapshot()["persisted"]
    assert "secret" not in json.dumps(diagnostics.snapshot())


@pytest.mark.parametrize("failure", ["exception", "cancelled"])
async def test_main_writes_terminal_receipt_and_releases_owner_on_failure(
    tmp_path, monkeypatch, failure
):
    settings = _settings(tmp_path / "lead.db")
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "configure_logging", lambda settings: None)

    async def fail(settings, **kwargs):
        if failure == "cancelled":
            raise asyncio.CancelledError()
        raise RuntimeError("secret-token")

    monkeypatch.setattr(main_module, "_run_owned", fail)
    with pytest.raises(asyncio.CancelledError if failure == "cancelled" else RuntimeError):
        await main_module.run(web_only=True)
    path = RuntimeDiagnostics(settings.database_url, "web-only").path
    receipt = json.loads(path.read_text())
    assert receipt["state"] == ("INTERRUPTED" if failure == "cancelled" else "FAILED")
    assert "secret-token" not in path.read_text()
    assert not any(task.get_name() == "lead-radar-heartbeat" for task in asyncio.all_tasks())
    with DatabaseRuntimeLock(settings.database_url) as ownership:
        assert ownership.exclusive


def test_json_exception_is_one_valid_json_line(monkeypatch):
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    monkeypatch.setenv("LOG_FORMAT", "json")
    try:
        configure_logging(SimpleNamespace(log_level="INFO"))
        try:
            raise RuntimeError('quoted "error"\nnewline')
        except RuntimeError:
            record = logging.LogRecord("probe", logging.ERROR, "", 1, "failed", (), sys.exc_info())
        output = root.handlers[0].formatter.format(record)
        assert len(output.splitlines()) == 1
        assert 'quoted "error"' in json.loads(output)["exception"]
    finally:
        root.handlers = handlers
        root.setLevel(level)


@pytest.mark.parametrize("previous_state", [None, "RUNNING", "FAILED", "INTERRUPTED"])
async def test_system_runtime_card_reports_facts_without_claiming_provider_readiness(
    session_factory, tmp_path, previous_state
):
    from httpx import ASGITransport, AsyncClient

    from tests.test_qa_smoke_pages import _app

    app = _app(session_factory)
    diagnostics = RuntimeDiagnostics(_settings(tmp_path / "lead.db").database_url, "web-only")
    diagnostics.start()
    diagnostics.ready()
    if previous_state:
        diagnostics.previous = {
            "state": previous_state,
            "unfinished": previous_state == "RUNNING",
            "heartbeat_at": "2026-10-08T00:00:00+00:00",
            "error_type": "<unsafe>",
        }
    app.state.runtime_diagnostics = diagnostics
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/system")
    assert response.status_code == 200
    card = response.text.split('id="server-runtime"', 1)[1].split("</section>", 1)[0]
    assert "доступность Instagram и OpenAI проверяется отдельно" in card
    assert "Работает" in card
    assert diagnostics.data["run_id"] not in card
    assert "<unsafe>" not in card
    if previous_state == "RUNNING":
        assert "Причина остановки неизвестна" in card
    elif previous_state == "FAILED":
        assert "&lt;unsafe&gt;" in card


def test_backup_readiness_uses_configured_database_directory(tmp_path, monkeypatch):
    import app.services.deployment_readiness_service as service

    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path / "unrelated-checkout")
    source = tmp_path / "data" / "lead.db"
    source.parent.mkdir()
    _database(source, "data")
    settings = _settings(source)
    assert not service.backup_present(settings)
    backup_sqlite_database(settings)
    assert service.backup_present(settings)


def test_backup_readiness_does_not_count_other_database_backup(tmp_path, monkeypatch):
    import app.services.deployment_readiness_service as service

    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    directory = tmp_path / ".backups"
    directory.mkdir()
    (directory / "unrelated-20000101.db").write_bytes(b"other")
    assert not service.backup_present(_settings(tmp_path / "lead.db"))


def test_backup_retention_failure_does_not_fail_successful_snapshot(tmp_path, monkeypatch):
    source = tmp_path / "lead.db"
    _database(source, "first")
    old = backup_sqlite_database(_settings(source))
    unlink = Path.unlink

    def fail_old(path, **kwargs):
        if path == old:
            raise PermissionError("old snapshot is open")
        return unlink(path, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_old)
    new = backup_sqlite_database(_settings(source, keep=1))
    assert _value(new) == "first"
    assert old.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("heartbeat_at", {}),
        ("mode", "secret-token"),
        ("exit_code", "secret-token"),
        ("state", []),
        ("reason", {}),
    ],
)
def test_malformed_lifecycle_values_are_not_republished(tmp_path, field, value):
    diagnostics = RuntimeDiagnostics(_settings(tmp_path / "lead.db").database_url, "web-only")
    diagnostics.start()
    malformed = json.loads(diagnostics.path.read_text())
    malformed[field] = value
    diagnostics.path.write_text(json.dumps(malformed))
    replacement = RuntimeDiagnostics(_settings(tmp_path / "lead.db").database_url, "web-only")
    replacement.start()
    assert replacement.snapshot()["previous"]["state"] == "UNREADABLE"
    assert "secret-token" not in replacement.path.read_text()


def test_force_killed_runtime_preserves_data_and_next_start_records_unclean_exit(tmp_path):
    source = tmp_path / "lead.db"
    _database(source, "saved-before-crash")
    url = _settings(source).database_url
    script = """
import asyncio, sys
from types import SimpleNamespace
from app import main
main.get_settings = lambda: SimpleNamespace(database_url=sys.argv[1], log_level='ERROR')
async def owned(settings, **kwargs):
    kwargs['diagnostics'].ready()
    print('READY', flush=True)
    if sys.argv[2] == 'hold':
        await asyncio.Event().wait()
    return 0
main._run_owned = owned
asyncio.run(main.run(web_only=True))
"""
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    process = subprocess.Popen(
        [sys.executable, "-c", script, url, "hold"],
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        # Bound the child startup wait; kill only this disposable test process.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(process.stdout.readline)
            try:
                assert pending.result(timeout=25).strip() == "READY"
            except BaseException:
                process.kill()
                raise
        receipt_path = RuntimeDiagnostics(url, "web-only").path
        assert json.loads(receipt_path.read_text())["state"] == "RUNNING"
        process.kill()
        process.communicate(timeout=10)
        assert _value(source) == "saved-before-crash"
        replacement = subprocess.run(
            [sys.executable, "-c", script, url, "finish"],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
        )
        assert replacement.returncode == 0, replacement.stderr
        receipt = json.loads(receipt_path.read_text())
        assert receipt["state"] == "STOPPED"
        assert receipt["previous"]["unfinished"] is True
        assert receipt["previous"]["reason"] is None
        assert _value(source) == "saved-before-crash"
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
