"""Authenticated in-app notifications router."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import AuthContext, UserRole, require_roles
from app.core.tenant_context import tenant_scoped_session
from app.models.operations import Notification

INBOX_ROLES: tuple[UserRole, ...] = ("owner", "admin", "agent")


class NotificationItem(BaseModel):
    """Single in-app notification row."""

    id: UUID
    type: str
    title: str
    body: str
    metadata: dict[str, object]
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    """List wrapper for recent tenant notifications."""

    items: list[NotificationItem]


def create_notifications_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> APIRouter:
    """Build tenant-isolated router for reading and acknowledging notifications."""
    router = APIRouter(prefix="/notifications", tags=["notifications"])
    inbox_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=INBOX_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(inbox_auth)]

    @router.get("", response_model=NotificationListResponse)
    async def list_notifications(auth: AuthDep) -> NotificationListResponse:
        async with tenant_scoped_session(session_factory, auth.tenant_id) as session:
            rows = (
                await session.execute(
                    select(Notification)
                    .where(Notification.tenant_id == auth.tenant_id)
                    .order_by(Notification.created_at.desc())
                    .limit(50)
                )
            ).scalars().all()
        return NotificationListResponse(
            items=[
                NotificationItem(
                    id=n.id,
                    type=n.type,
                    title=n.title,
                    body=n.body,
                    metadata=dict(n.payload or {}),
                    read_at=n.read_at,
                    created_at=n.created_at,
                )
                for n in rows
            ]
        )

    @router.post("/{notification_id}/read", response_model=NotificationItem)
    async def mark_read(notification_id: UUID, auth: AuthDep) -> NotificationItem:
        async with tenant_scoped_session(session_factory, auth.tenant_id) as session:
            row = (
                await session.execute(
                    select(Notification).where(
                        Notification.id == notification_id,
                        Notification.tenant_id == auth.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Notification not found",
                )
            if row.read_at is None:
                row.read_at = datetime.now(UTC)
            return NotificationItem(
                id=row.id,
                type=row.type,
                title=row.title,
                body=row.body,
                metadata=dict(row.payload or {}),
                read_at=row.read_at,
                created_at=row.created_at,
            )

    return router
