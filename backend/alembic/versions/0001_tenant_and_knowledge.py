"""Create pgvector extension, tenant tables, and knowledge base tables with indexes.

Revision ID: 0001_tenant_and_knowledge
Revises:
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_tenant_and_knowledge"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")
DEFAULT_KEYWORDS = sa.text("ARRAY['แอดมิน','คุยกับคน','ติดต่อเจ้าหน้าที่']")


def _tenant_col() -> sa.Column[object]:
    return sa.Column(
        "tenant_id",
        UUID,
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("plan", sa.String(64), nullable=False, server_default="trial"),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="trial"),
        sa.Column("pdpa_retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("auto_return_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('trial','active','trial_expired','past_due','suspended','canceled')",
            name="ck_tenants_status_valid",
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="owner"),
        sa.Column("is_super_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("role IN ('owner','admin','agent')", name="ck_users_role_valid"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "bot_settings",
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("shop_name", sa.String(255), nullable=False),
        sa.Column("tone", sa.String(64), nullable=False, server_default="สุภาพ เป็นกันเอง (ค่ะ)"),
        sa.Column(
            "greeting",
            sa.Text(),
            nullable=False,
            server_default="สวัสดีค่ะ มีอะไรให้ช่วยดูแลสอบถามได้เลยนะคะ",
        ),
        sa.Column(
            "handoff_keywords",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=DEFAULT_KEYWORDS,
        ),
        sa.Column("extra_instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "fallback_message",
            sa.Text(),
            nullable=False,
            server_default="ขออภัยค่ะ ข้อมูลส่วนนี้ขออนุญาตให้แอดมินตรวจสอบและติดต่อกลับนะคะ",
        ),
        sa.Column(
            "show_citations_to_customer",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "subscriptions",
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("plan", sa.String(64), nullable=False, server_default="trial"),
        sa.Column("status", sa.String(32), nullable=False, server_default="trialing"),
        sa.Column("omise_customer_id", sa.String(128), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('trialing','active','past_due','canceled','expired')",
            name="ck_subscriptions_status_valid",
        ),
    )

    op.create_table(
        "usage_monthly",
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("month", sa.String(7), primary_key=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "documents",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "status IN ('pending','processing','ready','failed')",
            name="ck_documents_status_valid",
        ),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])

    op.create_table(
        "chunks",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column(
            "document_id",
            UUID,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
    )
    op.create_index("ix_chunks_tenant_document", "chunks", ["tenant_id", "document_id"])
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_chunks_tsv_gin", "chunks", ["tsv"], postgresql_using="gin")


def downgrade() -> None:
    for table in [
        "chunks",
        "documents",
        "usage_monthly",
        "subscriptions",
        "bot_settings",
        "users",
        "tenants",
    ]:
        op.drop_table(table)
