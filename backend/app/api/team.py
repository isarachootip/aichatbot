"""Authenticated owner-only team management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import AuthContext, UserRole, require_roles
from app.schemas.team import (
    InviteTeamMemberRequest,
    TeamListResponse,
    TeamMemberResponse,
    UpdateMemberRoleRequest,
)
from app.services.team import (
    TeamConflictError,
    TeamMemberNotFoundError,
    invite_team_member,
    list_team_members,
    remove_team_member,
    update_member_role,
)

OWNER_ROLES: tuple[UserRole, ...] = ("owner",)


def create_team_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> APIRouter:
    """Build owner-only team invitation and RBAC role management router."""
    router = APIRouter(prefix="/team", tags=["team"])
    owner_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=OWNER_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(owner_auth)]

    @router.get("/users", response_model=TeamListResponse)
    async def get_team_users(auth: AuthDep) -> TeamListResponse:
        items = await list_team_members(session_factory, tenant_id=auth.tenant_id)
        return TeamListResponse(items=items)

    @router.post(
        "/invite",
        response_model=TeamMemberResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def invite_member(
        body: InviteTeamMemberRequest,
        auth: AuthDep,
    ) -> TeamMemberResponse:
        try:
            return await invite_team_member(
                session_factory,
                tenant_id=auth.tenant_id,
                email=body.email,
                role=body.role,
            )
        except TeamConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc

    @router.patch("/users/{member_id}/role", response_model=TeamMemberResponse)
    async def patch_member_role(
        member_id: UUID,
        body: UpdateMemberRoleRequest,
        auth: AuthDep,
    ) -> TeamMemberResponse:
        try:
            return await update_member_role(
                session_factory,
                tenant_id=auth.tenant_id,
                member_id=member_id,
                new_role=body.role,
            )
        except TeamMemberNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except TeamConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    @router.delete("/users/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_member(member_id: UUID, auth: AuthDep) -> Response:
        try:
            await remove_team_member(
                session_factory,
                tenant_id=auth.tenant_id,
                actor_user_id=auth.user_id,
                member_id=member_id,
            )
        except TeamMemberNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except TeamConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
