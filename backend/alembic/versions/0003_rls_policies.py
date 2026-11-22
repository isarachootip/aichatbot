"""Enable FORCE Row Level Security across all tenant tables and webhook lookup helper.

Revision ID: 0003_rls_policies
Revises: 0002_messaging_and_ops
Create Date: 2026-11-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_rls_policies"
down_revision: str | None = "0002_messaging_and_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES: tuple[str, ...] = (
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
)

ALL_RLS_TABLES: tuple[str, ...] = ("tenants", *TENANT_SCOPED_TABLES)
CURRENT_TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON tenants
            USING (id = {CURRENT_TENANT_EXPR})
            WITH CHECK (id = {CURRENT_TENANT_EXPR})
        """
    )

    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = {CURRENT_TENANT_EXPR})
                WITH CHECK (tenant_id = {CURRENT_TENANT_EXPR})
            """
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION resolve_channel_tenant(p_channel_id uuid)
        RETURNS uuid
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT tenant_id
            FROM channels
            WHERE id = p_channel_id AND active = true
            LIMIT 1;
        $$
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
                GRANT EXECUTE ON FUNCTION resolve_channel_tenant(uuid) TO app_user;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS resolve_channel_tenant(uuid)")

    for table in reversed(ALL_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
