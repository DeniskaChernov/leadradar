import ssl

from app.config import Settings
from app.db.session import create_engine, database_connect_args


def test_verify_full_uses_system_cas_and_hostname_validation():
    options = database_connect_args("postgresql+asyncpg://test:fake@unit.neon.tech/db?ssl=verify-full")
    context = options["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0


def test_other_explicit_tls_modes_and_sqlite_are_preserved():
    assert database_connect_args("sqlite+aiosqlite:///unit.db") == {"timeout": 30}
    assert database_connect_args("postgresql+asyncpg://localhost/unit?ssl=require") == {}
    assert database_connect_args("postgresql+asyncpg://localhost/unit") == {}


def test_app_engine_receives_verified_context(monkeypatch):
    captured = {}

    def factory(url, **options):
        captured.update(options)
        return "fake-engine"

    monkeypatch.setattr("app.db.session.create_async_engine", factory)
    settings = Settings(_env_file=None, database_url="postgresql+asyncpg://unit.neon.tech/db?ssl=verify-full")
    assert create_engine(settings) == "fake-engine"
    assert captured["connect_args"]["ssl"].check_hostname is True
    assert captured["connect_args"]["ssl"].verify_mode == ssl.CERT_REQUIRED
