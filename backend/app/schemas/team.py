"""Pydantic v2 schemas for tenant team member invitations and RBAC management."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.security import UserRole


class TeamMemberResponse(BaseModel):
    """Single dashboard team member belonging to a tenant."""

    id: UUID
    email: str
    role: UserRole
    created_at: datetime


class TeamListResponse(BaseModel):
    """Collection wrapper for tenant team members."""

    items: list[TeamMemberResponse]


class InviteTeamMemberRequest(BaseModel):
    """Invite payload adding a user email with an RBAC role to the tenant."""

    email: str = Field(min_length=3, max_length=320)
    role: UserRole = "agent"


class UpdateMemberRoleRequest(BaseModel):
    """Role update payload for an existing tenant team member."""

    role: UserRole
