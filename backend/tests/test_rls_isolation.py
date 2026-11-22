"""Tests proving PostgreSQL RLS enforces strict cross-tenant isolation."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.tenant_context import resolve_channel_tenant, tenant_scoped_session
from app.models import BotSetting, Chunk, Document, Message, Tenant
from tests.factories import seed_two_tenants


async def test_tenant_a_cannot_read_tenant_b_data(
    clean_database: None,
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Tenant A querying without WHERE filters only ever receives Tenant A's rows."""
    seeded = await seed_two_tenants(admin_session_factory)

    async with tenant_scoped_session(app_session_factory, seeded.tenant_a_id) as session:
        docs = (await session.scalars(select(Document))).all()
        chunks = (await session.scalars(select(Chunk))).all()
        messages = (await session.scalars(select(Message))).all()
        settings_rows = (await session.scalars(select(BotSetting))).all()

    assert [d.id for d in docs] == [seeded.doc_a_id]
    assert len(chunks) == 1
    assert chunks[0].tenant_id == seeded.tenant_a_id
    assert len(messages) == 1
    assert messages[0].tenant_id == seeded.tenant_a_id
    assert [s.tenant_id for s in settings_rows] == [seeded.tenant_a_id]


async def test_missing_tenant_context_fails_closed(
    clean_database: None,
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Queries executed without app.tenant_id set return zero rows (fail-closed)."""
    await seed_two_tenants(admin_session_factory)

    async with app_session_factory() as session, session.begin():
        docs = (await session.scalars(select(Document))).all()
        tenants = (await session.scalars(select(Tenant))).all()

    assert docs == []
    assert tenants == []


async def test_cross_tenant_insert_update_delete_blocked(
    clean_database: None,
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Tenant A cannot INSERT into Tenant B, nor UPDATE/DELETE Tenant B's rows."""
    seeded = await seed_two_tenants(admin_session_factory)

    with pytest.raises(ProgrammingError):
        async with tenant_scoped_session(app_session_factory, seeded.tenant_a_id) as session:
            session.add(
                Document(
                    tenant_id=seeded.tenant_b_id,
                    filename="injected.pdf",
                    mime="application/pdf",
                    storage_key="evil/injected.pdf",
                )
            )
            await session.flush()

    async with tenant_scoped_session(app_session_factory, seeded.tenant_a_id) as session:
        await session.execute(
            update(Document)
            .where(Document.id == seeded.doc_b_id)
            .values(filename="hacked.pdf")
        )
        await session.execute(delete(Document).where(Document.id == seeded.doc_b_id))

    async with tenant_scoped_session(app_session_factory, seeded.tenant_b_id) as session:
        doc_b = await session.scalar(select(Document).where(Document.id == seeded.doc_b_id))
        assert doc_b is not None
        assert doc_b.filename == "beta_secret.pdf"


async def test_pooled_connection_does_not_leak_tenant_context(
    clean_database: None,
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Transaction-local set_config clears automatically after transaction end."""
    seeded = await seed_two_tenants(admin_session_factory)

    async with tenant_scoped_session(app_session_factory, seeded.tenant_a_id) as session:
        assert len((await session.scalars(select(Document))).all()) == 1

    async with app_session_factory() as session, session.begin():
        assert (await session.scalars(select(Document))).all() == []


async def test_resolve_channel_tenant_helper(
    clean_database: None,
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SECURITY DEFINER helper resolves active channels and ignores inactive/unknown ones."""
    seeded = await seed_two_tenants(admin_session_factory)

    async with app_session_factory() as session, session.begin():
        resolved_active = await resolve_channel_tenant(session, seeded.channel_a_id)
        resolved_inactive = await resolve_channel_tenant(session, seeded.inactive_channel_b_id)
        resolved_missing = await resolve_channel_tenant(session, uuid4())

    assert resolved_active == seeded.tenant_a_id
    assert resolved_inactive is None
    assert resolved_missing is None
