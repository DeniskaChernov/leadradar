import socket

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import OutboundNetworkForbiddenError
from app.db.base import Base


@pytest.fixture(autouse=True)
def block_outbound_network(monkeypatch):
    """Guarantees zero paid calls, zero tokens, and zero outbound network access during test runs."""
    orig_connect = socket.socket.connect

    def guarded_connect(self, address):
        if isinstance(address, tuple) and len(address) >= 2:
            host, _ = address[0], address[1]
            if host in {"127.0.0.1", "localhost", "::1", "0.0.0.0", "testserver"}:
                return orig_connect(self, address)
        elif isinstance(address, str) and (address.startswith("\x00") or "sqlite" in address or "test" in address):
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


