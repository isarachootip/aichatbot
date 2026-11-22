"""Tenant, user, bot settings, subscription, and usage ORM models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at_col, uuid_pk


class Tenant(Base):
    """Shop tenant owning isolated knowledge, channels, and conversations."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "status IN ('trial', 'active', 'trial_expired', 'past_due', 'suspended', 'canceled')",
            name="status_valid",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(64), nullable=False, default="trial")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="trial")
    pdpa_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    auto_return_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    created_at: Mapped[datetime] = created_at_col()


class User(Base):
    """Authenticated dashboard member belonging to a single tenant."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'admin', 'agent')", name="role_valid"),
    )

    id: Mapped[UUID] = uuid_pk()
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="owner")
    is_super_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()


class BotSetting(Base):
    """Per-tenant AI persona, greeting, fallback, and handoff configuration."""

    __tablename__ = "bot_settings"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False)
    tone: Mapped[str] = mapped_column(String(64), nullable=False, default="สุภาพ เป็นกันเอง (ค่ะ)")
    greeting: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="สวัสดีค่ะ มีอะไรให้ช่วยดูแลสอบถามได้เลยนะคะ",
    )
    handoff_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=lambda: ["แอดมิน", "คุยกับคน", "ติดต่อเจ้าหน้าที่"],
    )
    extra_instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fallback_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="ขออภัยค่ะ ข้อมูลส่วนนี้ขออนุญาตให้แอดมินตรวจสอบและติดต่อกลับนะคะ",
    )
    show_citations_to_customer: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    handoff_notify_channel_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("channels.id", ondelete="SET NULL"),
        nullable=True,
    )
    handoff_notify_target_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )


class Subscription(Base):
    """Omise billing subscription state for a tenant."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'canceled', 'expired')",
            name="status_valid",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    plan: Mapped[str] = mapped_column(String(64), nullable=False, default="trial")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="trialing")
    omise_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class UsageMonthly(Base):
    """Monthly message and LLM token usage rollup per tenant."""

    __tablename__ = "usage_monthly"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
