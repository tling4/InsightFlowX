import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# JWT_SECRET_KEY is required (no default). Set before any config import.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db.base import Base
from app.db.session import get_async_session
from app.services.rate_limiter import login_rate_limit, register_rate_limit


async def _noop_rate_limit():
    pass


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def client():
    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_async_session():
        async with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[login_rate_limit] = _noop_rate_limit
    app.dependency_overrides[register_rate_limit] = _noop_rate_limit

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()
