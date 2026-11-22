"""Health endpoint router verifying PostgreSQL and Redis readiness."""

from fastapi import APIRouter, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.database import check_database_health
from app.schemas.health import DependencyStatus, HealthResponse


async def _check_redis_health(redis_client: Redis) -> bool:
    """Verify Redis connectivity via PING."""
    try:
        pong = await redis_client.ping()
        return bool(pong)
    except Exception:
        return False


def create_health_router(
    *,
    engine: AsyncEngine,
    redis_client: Redis,
    app_version: str,
) -> APIRouter:
    """Build the health router bound to live database and Redis handles."""
    router = APIRouter(tags=["health"])

    @router.get("/health", response_model=HealthResponse)
    async def health_check(response: Response) -> HealthResponse:
        db_ok = await check_database_health(engine)
        redis_ok = await _check_redis_health(redis_client)

        db_status: DependencyStatus = "ok" if db_ok else "error"
        redis_status: DependencyStatus = "ok" if redis_ok else "error"
        overall_ok = db_ok and redis_ok

        if not overall_ok:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

        return HealthResponse(
            status="ok" if overall_ok else "degraded",
            database=db_status,
            redis=redis_status,
            version=app_version,
        )

    return router
