"""Tests verifying Alembic schema migrations, pgvector, indexes, and RLS flags."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

EXPECTED_TABLES: set[str] = {
    "tenants",
    "users",
    "bot_settings",
    "subscriptions",
    "usage_monthly",
    "documents",
    "chunks",
    "channels",
    "conversations",
    "messages",
    "unanswered_questions",
    "webhook_events",
    "notifications",
}


async def test_pgvector_extension_and_all_tables_exist(admin_engine: AsyncEngine) -> None:
    """Verify pgvector extension and all 13 application tables exist."""
    async with admin_engine.connect() as conn:
        ext_res = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        assert ext_res.scalar_one_or_none() == "vector"

        tbl_res = await conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        existing_tables = {row[0] for row in tbl_res.fetchall()}

    assert EXPECTED_TABLES.issubset(existing_tables)


async def test_chunks_hnsw_and_gin_indexes_exist(admin_engine: AsyncEngine) -> None:
    """Verify chunks table has both HNSW vector index and GIN tsvector index."""
    async with admin_engine.connect() as conn:
        idx_res = await conn.execute(
            text(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = 'chunks'
                """
            )
        )
        indexes = {row[0]: str(row[1]) for row in idx_res.fetchall()}

    assert "ix_chunks_embedding_hnsw" in indexes
    assert "USING hnsw" in indexes["ix_chunks_embedding_hnsw"]
    assert "vector_cosine_ops" in indexes["ix_chunks_embedding_hnsw"]

    assert "ix_chunks_tsv_gin" in indexes
    assert "USING gin" in indexes["ix_chunks_tsv_gin"]


async def test_rls_enabled_and_forced_on_all_tenant_tables(admin_engine: AsyncEngine) -> None:
    """Verify every tenant-owned table has ENABLE and FORCE ROW LEVEL SECURITY."""
    async with admin_engine.connect() as conn:
        res = await conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                """
            )
        )
        rls_flags = {row[0]: (bool(row[1]), bool(row[2])) for row in res.fetchall()}

    for table in EXPECTED_TABLES:
        assert rls_flags[table] == (True, True), f"RLS not forced on {table}"


async def test_app_user_is_non_superuser_without_bypassrls(admin_engine: AsyncEngine) -> None:
    """Ensure app_user cannot silently bypass PostgreSQL RLS policies."""
    async with admin_engine.connect() as conn:
        res = await conn.execute(
            text(
                """
                SELECT rolsuper, rolbypassrls
                FROM pg_roles
                WHERE rolname = 'app_user'
                """
            )
        )
        row = res.one()

    assert row[0] is False
    assert row[1] is False
