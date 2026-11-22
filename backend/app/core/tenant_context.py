"""Transaction-scoped PostgreSQL Row Level Security (RLS) tenant helpers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Bind app.tenant_id locally to the active PostgreSQL transaction.

    Uses is_local=true so pooled connections never leak tenant context
    into subsequent transactions after commit or rollback.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


@asynccontextmanager
async def tenant_scoped_session(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
) -> AsyncIterator[AsyncSession]:
    """Open a transaction with PostgreSQL RLS locked to a single tenant."""
    async with session_factory() as session, session.begin():
        await set_tenant_context(session, tenant_id)
        yield session


async def resolve_channel_tenant(
    session: AsyncSession,
    channel_id: UUID,
) -> UUID | None:
    """Resolve the owning tenant_id of an active channel via SECURITY DEFINER SQL."""
    result = await session.execute(
        text("SELECT resolve_channel_tenant(:channel_id)"),
        {"channel_id": str(channel_id)},
    )
    resolved: UUID | None = result.scalar_one_or_none()
    return resolved
