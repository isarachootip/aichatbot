"""Add SECURITY DEFINER email lookup helper for signup and dev login under FORCE RLS.

Revision ID: 0006_auth_email_lookup
Revises: 0005_handoff_notify_rls
Create Date: 2026-11-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_auth_email_lookup"
down_revision: str | None = "0005_handoff_notify_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION resolve_user_by_email(p_email text)
        RETURNS TABLE(user_id uuid, tenant_id uuid, role text)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT u.id, u.tenant_id, u.role::text
            FROM users u
            WHERE lower(u.email) = lower(p_email)
            LIMIT 1;
        $$
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                GRANT EXECUTE ON FUNCTION resolve_user_by_email(text) TO app_user;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS resolve_user_by_email(text)")
