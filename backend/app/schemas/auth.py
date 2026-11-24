"""Pydantic v2 schemas for signup, dev login, and authenticated profile (/me)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.security import UserRole


class SignupRequest(BaseModel):
    """Self-serve shop signup creating a 7-day free trial tenant and owner user."""

    shop_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=320)
    user_id: UUID | None = None


class DevLoginRequest(BaseModel):
    """Development/test-only email sign-in payload for local dashboard testing."""

    email: str = Field(min_length=3, max_length=320)


class AuthTokenResponse(BaseModel):
    """Issued auth identity and optional dev JWT access token."""

    access_token: str | None = None
    token_type: str = "bearer"
    user_id: UUID
    tenant_id: UUID
    email: str
    role: UserRole
    shop_name: str
    trial_ends_at: datetime | None = None


class MeResponse(BaseModel):
    """Current authenticated user, tenant trial status, plan quota, and notifications."""

    user_id: UUID
    tenant_id: UUID
    email: str
    role: UserRole
    is_super_admin: bool
    shop_name: str
    plan: str
    status: str
    trial_ends_at: datetime | None
    trial_days_remaining: int
    used_messages: int
    limit_messages: int
    max_channels: int
    max_documents: int
    unread_notifications: int
