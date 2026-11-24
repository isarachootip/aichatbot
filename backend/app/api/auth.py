"""Auth router: self-serve 7-day trial signup, dev login, and /me profile."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import AuthContext, UserRole, require_roles
from app.schemas.auth import AuthTokenResponse, DevLoginRequest, MeResponse, SignupRequest
from app.services.auth import (
    EmailAlreadyRegisteredError,
    UserNotFoundError,
    dev_login_by_email,
    get_me_summary,
    signup_shop,
)

ALL_ROLES: tuple[UserRole, ...] = ("owner", "admin", "agent")


def create_auth_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> APIRouter:
    """Build signup, local dev login, and authenticated /me endpoints."""
    router = APIRouter(tags=["auth"])
    any_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=ALL_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(any_auth)]

    @router.post(
        "/signup",
        response_model=AuthTokenResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def signup(body: SignupRequest) -> AuthTokenResponse:
        try:
            return await signup_shop(
                session_factory,
                settings,
                shop_name=body.shop_name,
                email=body.email,
                user_id=body.user_id,
            )
        except EmailAlreadyRegisteredError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @router.post("/auth/dev-login", response_model=AuthTokenResponse)
    async def dev_login(body: DevLoginRequest) -> AuthTokenResponse:
        try:
            return await dev_login_by_email(session_factory, settings, email=body.email)
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        except UserNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @router.get("/me", response_model=MeResponse)
    async def me(auth: AuthDep) -> MeResponse:
        return await get_me_summary(session_factory, auth)

    return router
