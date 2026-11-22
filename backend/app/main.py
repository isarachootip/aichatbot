"""FastAPI application factory and ASGI entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.conversations import create_conversations_router
from app.api.health import create_health_router
from app.api.webhooks import create_webhooks_router
from app.channels.factory import ChannelAdapterFactory, DatabaseChannelAdapterFactory
from app.core.config import Settings, get_settings
from app.core.database import create_engine_from_url, create_session_factory
from app.core.logging import configure_logging, get_logger
from app.core.queue import ArqJobEnqueuer, JobEnqueuer
from app.services.debounce import BurstDebouncer, RedisBurstDebouncer


def create_app(
    settings: Settings | None = None,
    *,
    enqueuer: JobEnqueuer | None = None,
    debouncer: BurstDebouncer | None = None,
    adapter_factory: ChannelAdapterFactory | None = None,
) -> FastAPI:
    """Construct and configure the FastAPI application."""
    cfg = settings or get_settings()
    configure_logging(cfg.log_level)
    logger = get_logger("app.main")

    engine = create_engine_from_url(cfg.database_url)
    session_factory = create_session_factory(engine)
    redis_client = Redis.from_url(cfg.redis_url, decode_responses=True)
    job_enqueuer: JobEnqueuer = enqueuer or ArqJobEnqueuer(cfg.redis_url)
    burst_debouncer: BurstDebouncer = debouncer or RedisBurstDebouncer(redis_client)
    outbound_adapters: ChannelAdapterFactory = adapter_factory or DatabaseChannelAdapterFactory(
        session_factory,
        fernet_key=cfg.fernet_key,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("application_startup", env=cfg.app_env, version=cfg.app_version)
        try:
            yield
        finally:
            await job_enqueuer.close()
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
    application.include_router(
        create_webhooks_router(
            session_factory=session_factory,
            enqueuer=job_enqueuer,
            debouncer=burst_debouncer,
        )
    )
    application.include_router(
        create_conversations_router(
            session_factory=session_factory,
            adapter_factory=outbound_adapters,
            settings=cfg,
        )
    )
    return application


app = create_app()
