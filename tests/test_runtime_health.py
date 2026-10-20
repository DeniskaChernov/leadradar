import asyncio
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.config import Settings
from app.db.session import create_engine, create_session_factory
from app.services.deployment_readiness_service import inspect_runtime_readiness
from tests.test_web_security import _build_test_app


@pytest.mark.asyncio
async def test_platform_probe_is_public_queries_database_and_rejects_old_revision(
    migrated_database, monkeypatch,
):
    def forbidden(*args, **kwargs):
        pytest.fail("A frequent platform probe must not run a full schema audit")

    monkeypatch.setattr("app.services.deployment_readiness_service.command.check", forbidden)
    settings = Settings(_env_file=None, web_auth_enabled=True, telegram_admin_chat_ids=[101],
                        web_session_secret="test-probe-secret-" * 3)
    engine = create_engine(settings)
    try:
        factory = create_session_factory(engine)
        app = _build_test_app(settings, factory)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            ready = await client.get("/health/runtime")
            assert ready.status_code == 200
            assert ready.json() == {"ok": True, "database_healthy": True, "migration_at_head": True}
            async with engine.begin() as c:
                await c.execute(text("UPDATE alembic_version SET version_num='old-revision'"))
            stale = await client.get("/health/runtime")
            assert stale.status_code == 503
            assert stale.json()["database_healthy"] is True
            assert stale.json()["migration_at_head"] is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_platform_probe_missing_schema_does_not_report_ready_or_leak_errors(session_factory):
    assert await inspect_runtime_readiness(session_factory) == {
        "ok": False, "database_healthy": False, "migration_at_head": False,
    }


@pytest.mark.asyncio
async def test_slow_database_is_bounded():
    @asynccontextmanager
    async def stalled_session():
        await asyncio.sleep(10)
        yield None

    result = await asyncio.wait_for(inspect_runtime_readiness(stalled_session, timeout_seconds=0.01), 1)
    assert result["ok"] is False
