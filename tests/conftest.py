import socket

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import OutboundNetworkForbiddenError
from app.db.base import Base
from app.db.models import ProviderBudgetPolicy


async def seed_scrapecreators_instagram_policy(
    session_factory,
    *,
    hard: int = 3800,
    target: int = 3000,
    soft: int = 3500,
) -> None:
    """Минимальная active monthly policy для paid scrapecreators/instagram тестов."""
    async with session_factory() as session:
        session.add(
            ProviderBudgetPolicy(
                provider="scrapecreators",
                service="instagram",
                monthly_target_units=target,
                monthly_soft_limit_units=soft,
                monthly_hard_limit_units=hard,
                default_scan_budget_units=5,
                maximum_manual_scan_budget_units=50,
                target_minimum_months=6,
                comments_target_units=1,
                discovery_target_units=1,
                enrichment_target_units=0,
                reserve_target_units=1,
                active=True,
            )
        )
        await session.commit()


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch):
    """Guarantees zero paid calls, zero tokens, and zero outbound network access during test runs."""
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        if isinstance(address, tuple) and len(address) >= 2:
            host, _ = address[0], address[1]
            if host in {"127.0.0.1", "localhost", "::1", "0.0.0.0", "testserver"}:
                return orig_connect(self, address)
        elif isinstance(address, str) and (
            address.startswith("\x00") or "sqlite" in address or "test" in address
        ):
            return orig_connect(self, address)
        raise OutboundNetworkForbiddenError(
            f"Outbound network connection forbidden in test suite! Attempted connect to: {address}. "
            "Automated tests must be 100% offline with zero live network calls."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def file_session_factory(tmp_path):
    """SQLite fixture with independent connections for real worker-race tests."""

    database_path = (tmp_path / "worker-race.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()
