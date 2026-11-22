"""FastAPI application factory and ASGI entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.health import create_health_router
from app.core.config import Settings, get_settings
from app.core.database import create_engine_from_url
from app.core.logging import configure_logging, get_logger


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI application."""
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)
    logger = get_logger("app.main")

    engine = create_engine_from_url(cfg.database_url)
    redis_client = Redis.from_url(cfg.redis_url, decode_responses=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("application_startup", env=cfg.app_env, version=cfg.app_version)
        try:
            yield
        finally:
            await redis_client.aclose()
            await engine.dispose()
            logger.info("application_shutdown")

    application = FastAPI(
        title="Thai AI Chat Agent SaaS",
        version=cfg.app_version,
        lifespan=lifespan,
    )
    application.include_router(
        create_health_router(
            engine=engine,
            redis_client=redis_client,
            app_version=cfg.app_version,
        )
    )
    return application


app = create_app()
