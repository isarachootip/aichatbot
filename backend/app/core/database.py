"""Async SQLAlchemy engine and session helpers."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_from_url(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create a pooled async SQLAlchemy engine."""
    return create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the given engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def check_database_health(engine: AsyncEngine) -> bool:
    """Verify PostgreSQL connectivity via a lightweight SELECT 1 query."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return bool(result.scalar_one() == 1)
    except Exception:
        return False
