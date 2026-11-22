"""ARQ worker settings and lifecycle hooks for background jobs."""

from collections.abc import Callable, Coroutine
from typing import ClassVar

from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import get_settings
from app.core.database import create_engine_from_url, create_session_factory
from app.core.logging import configure_logging, get_logger
from app.core.storage import S3ObjectStorage
from app.rag.embeddings import create_embedder
from app.workers.ingest import ingest_document_job

WorkerTask = Callable[..., Coroutine[object, object, object]]


async def worker_ping(_ctx: dict[str, object]) -> str:
    """Lightweight diagnostic task proving the ARQ worker can process jobs."""
    return "pong"


async def on_startup(ctx: dict[str, object]) -> None:
    """Initialize logging, DB pool, S3 storage, and embedder on worker boot."""
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine_from_url(settings.database_url)
    ctx["settings"] = settings
    ctx["engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["storage"] = S3ObjectStorage.from_settings(settings)
    ctx["embedder"] = create_embedder(settings)
    get_logger("app.workers").info(
        "arq_worker_startup",
        env=settings.app_env,
        embedding_provider=settings.embedding_provider,
    )


async def on_shutdown(ctx: dict[str, object]) -> None:
    """Cleanly dispose async DB connections on worker shutdown."""
    engine = ctx.get("engine")
    if isinstance(engine, AsyncEngine):
        await engine.dispose()
    get_logger("app.workers").info("arq_worker_shutdown")


class WorkerSettings:
    """ARQ entrypoint (`arq app.workers.settings.WorkerSettings`)."""

    functions: ClassVar[list[WorkerTask]] = [worker_ping, ingest_document_job]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
