"""Authenticated bot settings endpoints (GET/PUT /settings/bot)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import AuthContext, UserRole, require_roles
from app.schemas.bot_settings import BotSettingsResponse, UpdateBotSettingsRequest
from app.services.bot_settings import get_bot_settings, update_bot_settings

ADMIN_ROLES: tuple[UserRole, ...] = ("owner", "admin")


def create_bot_settings_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> APIRouter:
    """Build tenant-isolated router for viewing and editing bot settings."""
    router = APIRouter(prefix="/settings", tags=["settings"])
    admin_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=ADMIN_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(admin_auth)]

    @router.get("/bot", response_model=BotSettingsResponse)
    async def read_bot_settings(auth: AuthDep) -> BotSettingsResponse:
        return await get_bot_settings(session_factory, tenant_id=auth.tenant_id)

    @router.put("/bot", response_model=BotSettingsResponse)
    async def save_bot_settings(
        body: UpdateBotSettingsRequest,
        auth: AuthDep,
    ) -> BotSettingsResponse:
        try:
            return await update_bot_settings(
                session_factory,
                tenant_id=auth.tenant_id,
                payload=body,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    return router
