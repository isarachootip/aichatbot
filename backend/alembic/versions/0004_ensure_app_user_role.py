"""Idempotently ensure non-superuser app_user role and grants exist on any Postgres volume.

Revision ID: 0004_ensure_app_user_role
Revises: 0003_rls_policies
Create Date: 2026-11-22
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0004_ensure_app_user_role"
down_revision: str | None = "0003_rls_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    app_password = os.getenv("APP_DB_PASSWORD", "app_dev_password").replace("'", "''")

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                CREATE ROLE app_user LOGIN PASSWORD '{app_password}'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;

            EXECUTE format('GRANT CONNECT ON DATABASE %I TO app_user', current_database());
        END
        $$;
        """
    )

    op.execute("GRANT USAGE ON SCHEMA public TO app_user")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user")
    op.execute("GRANT EXECUTE ON FUNCTION resolve_channel_tenant(uuid) TO app_user")
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO app_user
        """
    )


def downgrade() -> None:
    # Role is cluster-wide and shared across databases; leave intact on downgrade.
    pass
