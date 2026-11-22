"""Create messaging, webhook idempotency, and notification tables.

Revision ID: 0002_messaging_and_ops
Revises: 0001_tenant_and_knowledge
Create Date: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_messaging_and_ops"
down_revision: str | None = "0001_tenant_and_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
NOW = sa.text("now()")


def _tenant_col() -> sa.Column[object]:
    return sa.Column(
        "tenant_id",
        UUID,
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column("webhook_secret", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "type IN ('line','facebook','instagram','web')",
            name="ck_channels_type_valid",
        ),
    )
    op.create_index("ix_channels_tenant_id", "channels", ["tenant_id"])

    op.create_table(
        "conversations",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column(
            "channel_id",
            UUID,
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("customer_name", sa.String(255), nullable=True),
        sa.Column("mode", sa.String(16), nullable=False, server_default="bot"),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=NOW,
        ),
        sa.Column("last_agent_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("mode IN ('bot','human')", name="ck_conversations_mode_valid"),
        sa.UniqueConstraint(
            "tenant_id",
            "channel_id",
            "external_user_id",
            name="uq_conversations_tenant_channel_ext_user",
        ),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])

    op.create_table(
        "messages",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column(
            "conversation_id",
            UUID,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "sources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.CheckConstraint("role IN ('customer','bot','agent')", name="ck_messages_role_valid"),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "unanswered_questions",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column(
            "conversation_id",
            UUID,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_unanswered_questions_tenant_id", "unanswered_questions", ["tenant_id"])

    op.create_table(
        "webhook_events",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column(
            "channel_id",
            UUID,
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_event_id", sa.String(255), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint(
            "channel_id",
            "external_event_id",
            name="uq_webhook_events_channel_external_event",
        ),
    )
    op.create_index("ix_webhook_events_tenant_id", "webhook_events", ["tenant_id"])

    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True),
        _tenant_col(),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])


def downgrade() -> None:
    for table in [
        "notifications",
        "webhook_events",
        "unanswered_questions",
        "messages",
        "conversations",
        "channels",
    ]:
        op.drop_table(table)
