"""Shared pytest fixtures for database migrations, RLS roles, and HTTP testing."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import create_engine_from_url, create_session_factory
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Return test-scoped application settings pointing to chatbot_test."""
    base = get_settings()
    return base.model_copy(
        update={
            "app_env": "test",
            "database_url": base.test_database_url,
            "database_migration_url": base.test_database_migration_url,
        }
    )


@pytest.fixture(scope="session", autouse=True)
def apply_test_migrations(test_settings: Settings) -> None:
    """Apply Alembic migrations to the test database before running tests."""
    env = os.environ.copy()
    env["DATABASE_MIGRATION_URL"] = test_settings.test_database_migration_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic upgrade failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
        )


@pytest_asyncio.fixture(scope="session")
async def admin_engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Owner/superuser engine for seeding fixtures and inspecting pg_catalog."""
    engine = create_engine_from_url(test_settings.test_database_migration_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def app_engine(test_settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Non-superuser app_user engine where PostgreSQL FORCE RLS is enforced."""
    engine = create_engine_from_url(test_settings.test_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def admin_session_factory(admin_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory connected as table owner for test setup/teardown."""
    return create_session_factory(admin_engine)


@pytest.fixture(scope="session")
def app_session_factory(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory connected as non-superuser app_user for RLS verification."""
    return create_session_factory(app_engine)


@pytest_asyncio.fixture
async def clean_database(admin_engine: AsyncEngine) -> AsyncIterator[None]:
    """Ensure a clean tenant table before and after each test."""
    async with admin_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE tenants CASCADE"))
    yield
    async with admin_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE tenants CASCADE"))


@pytest_asyncio.fixture
async def api_client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    """Async HTTP test client bound to the FastAPI app with full lifespan."""
    application = create_app(test_settings)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client,
    ):
        yield client
