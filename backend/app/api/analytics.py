"""Authenticated analytics summary router (admin and owner)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import AuthContext, UserRole, require_roles
from app.schemas.analytics import AnalyticsSummaryResponse
from app.services.analytics import get_analytics_summary

ADMIN_ROLES: tuple[UserRole, ...] = ("owner", "admin")


def create_analytics_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> APIRouter:
    """Build tenant-isolated analytics summary router."""
    router = APIRouter(prefix="/analytics", tags=["analytics"])
    admin_auth = require_roles(
        session_factory=session_factory,
        settings=settings,
        allowed_roles=ADMIN_ROLES,
    )
    AuthDep = Annotated[AuthContext, Depends(admin_auth)]

    @router.get("/summary", response_model=AnalyticsSummaryResponse)
    async def analytics_summary(
        auth: AuthDep,
        days: Annotated[int, Query(ge=1, le=90)] = 14,
    ) -> AnalyticsSummaryResponse:
        return await get_analytics_summary(
            session_factory,
            tenant_id=auth.tenant_id,
            days=days,
        )

    return router
