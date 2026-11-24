"""FastAPI application factory and ASGI entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.api.analytics import create_analytics_router
from app.api.auth import create_auth_router
from app.api.bot_settings import create_bot_settings_router
from app.api.channels import create_channels_router
from app.api.conversations import create_conversations_router
from app.api.documents import create_documents_router
from app.api.health import create_health_router
from app.api.notifications import create_notifications_router
from app.api.playground import create_playground_router
from app.api.team import create_team_router
from app.api.webhooks import create_webhooks_router
from app.channels.factory import ChannelAdapterFactory, DatabaseChannelAdapterFactory
from app.core.config import Settings, get_settings
from app.core.database import create_engine_from_url, create_session_factory
from app.core.logging import configure_logging, get_logger
from app.core.queue import ArqJobEnqueuer, JobEnqueuer
from app.core.storage import ObjectStorage, S3ObjectStorage
from app.rag.embeddings import Embedder
from app.rag.llm import LLMClient
from app.services.channels import ChannelTester, HttpxChannelTester
from app.services.debounce import BurstDebouncer, RedisBurstDebouncer


def create_app(
    settings: Settings | None = None,
    *,
    enqueuer: JobEnqueuer | None = None,
    debouncer: BurstDebouncer | None = None,
    adapter_factory: ChannelAdapterFactory | None = None,
    storage: ObjectStorage | None = None,
    embedder: Embedder | None = None,
    llm_client: LLMClient | None = None,
    channel_tester: ChannelTester | None = None,
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
    object_storage: ObjectStorage = storage or S3ObjectStorage.from_settings(cfg)
    tester: ChannelTester = channel_tester or HttpxChannelTester()
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
    allowed_origins = [o.strip() for o in cfg.cors_origins.split(",") if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(
        create_health_router(engine=engine, redis_client=redis_client, app_version=cfg.app_version)
    )
    application.include_router(create_auth_router(session_factory=session_factory, settings=cfg))
    application.include_router(
        create_documents_router(
            session_factory=session_factory,
            storage=object_storage,
            enqueuer=job_enqueuer,
            settings=cfg,
        )
    )
    application.include_router(
        create_channels_router(session_factory=session_factory, settings=cfg, tester=tester)
    )
    application.include_router(
        create_bot_settings_router(session_factory=session_factory, settings=cfg)
    )
    application.include_router(
        create_playground_router(
            session_factory=session_factory,
            settings=cfg,
            embedder=embedder,
            llm_client=llm_client,
        )
    )
    application.include_router(
        create_conversations_router(
            session_factory=session_factory,
            adapter_factory=outbound_adapters,
            settings=cfg,
        )
    )
    application.include_router(
        create_notifications_router(session_factory=session_factory, settings=cfg)
    )
    application.include_router(
        create_analytics_router(session_factory=session_factory, settings=cfg)
    )
    application.include_router(create_team_router(session_factory=session_factory, settings=cfg))
    application.include_router(
        create_webhooks_router(
            session_factory=session_factory,
            enqueuer=job_enqueuer,
            debouncer=burst_debouncer,
        )
    )
    return application


app = create_app()
