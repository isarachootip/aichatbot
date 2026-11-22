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


async def list_active_tenant_ids(session: AsyncSession) -> list[UUID]:
    """Enumerate all tenant IDs via SECURITY DEFINER SQL for RLS-safe cron iteration."""
    result = await session.execute(text("SELECT list_active_tenant_ids()"))
    return [row[0] for row in result.fetchall() if row[0] is not None]


async def resolve_user_tenant(
    session: AsyncSession,
    user_id: UUID,
) -> tuple[UUID, str] | None:
    """Resolve (tenant_id, role) for an authenticated user via SECURITY DEFINER SQL."""
    result = await session.execute(
        text("SELECT tenant_id, role FROM resolve_user_tenant(:user_id)"),
        {"user_id": str(user_id)},
    )
    row = result.one_or_none()
    if row is None:
        return None
    return (row[0], str(row[1]))
