"""Add handoff notify target columns to bot_settings and RLS SECURITY DEFINER helpers.

Revision ID: 0005_handoff_notify_rls
Revises: 0004_ensure_app_user_role
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0005_handoff_notify_rls"
down_revision: str | None = "0004_ensure_app_user_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bot_settings",
        sa.Column(
            "handoff_notify_channel_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "bot_settings",
        sa.Column("handoff_notify_target_id", sa.String(length=255), nullable=True),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION list_active_tenant_ids()
        RETURNS SETOF uuid
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT id
            FROM tenants
            ORDER BY created_at ASC;
        $$
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION resolve_user_tenant(p_user_id uuid)
        RETURNS TABLE(tenant_id uuid, role text)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT u.tenant_id, u.role::text
            FROM users u
            WHERE u.id = p_user_id
            LIMIT 1;
        $$
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                GRANT EXECUTE ON FUNCTION list_active_tenant_ids() TO app_user;
                GRANT EXECUTE ON FUNCTION resolve_user_tenant(uuid) TO app_user;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS resolve_user_tenant(uuid)")
    op.execute("DROP FUNCTION IF EXISTS list_active_tenant_ids()")
    op.drop_column("bot_settings", "handoff_notify_target_id")
    op.drop_column("bot_settings", "handoff_notify_channel_id")
