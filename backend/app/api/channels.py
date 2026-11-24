"""Authenticated messaging channel management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import AuthContext, UserRole, require_roles
from app.schemas.channels import (
    ChannelListResponse,
    ChannelResponse,
    ChannelTestResponse,
    CreateLineChannelRequest,
)
from app.services.channels import (
    ChannelLimitExceededError,
    ChannelNotFoundError,
    ChannelTester,
    create_line_channel,
    delete_channel,
    list_channels,
    test_channel_connection,
)

ADMIN_ROLES: tuple[UserRole, ...] = ("owner", "admin")


def create_channels_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    tester: ChannelTester,
) -> APIRouter:
    """Build tenant-isolated router for connecting and testing LINE channels."""
    router = APIRouter(prefix="/channels", tags=["channels"])
    admin_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=ADMIN_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(admin_auth)]

    @router.get("", response_model=ChannelListResponse)
    async def get_channels(auth: AuthDep) -> ChannelListResponse:
        items = await list_channels(session_factory, settings, tenant_id=auth.tenant_id)
        return ChannelListResponse(items=items)

    @router.post(
        "",
        response_model=ChannelResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_line_channel(
        body: CreateLineChannelRequest,
        auth: AuthDep,
    ) -> ChannelResponse:
        try:
            return await create_line_channel(
                session_factory,
                settings,
                tenant_id=auth.tenant_id,
                name=body.name,
                channel_access_token=body.channel_access_token,
                webhook_secret=body.webhook_secret,
            )
        except ChannelLimitExceededError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @router.post("/{channel_id}/test", response_model=ChannelTestResponse)
    async def probe_channel(channel_id: UUID, auth: AuthDep) -> ChannelTestResponse:
        try:
            return await test_channel_connection(
                session_factory,
                settings,
                tester,
                tenant_id=auth.tenant_id,
                channel_id=channel_id,
            )
        except ChannelNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    @router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_channel(channel_id: UUID, auth: AuthDep) -> Response:
        try:
            await delete_channel(session_factory, tenant_id=auth.tenant_id, channel_id=channel_id)
        except ChannelNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
