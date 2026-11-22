"""ARQ worker settings scaffold for Phase 1+ background jobs."""

from collections.abc import Callable, Coroutine
from typing import ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

WorkerTask = Callable[[dict[str, object]], Coroutine[object, object, object]]


async def worker_ping(_ctx: dict[str, object]) -> str:
    """Lightweight diagnostic task proving the ARQ worker can process jobs."""
    return "pong"


async def on_startup(_ctx: dict[str, object]) -> None:
    """Initialize structured logging when the ARQ worker boots."""
    settings = get_settings()
    configure_logging(settings.log_level)
    get_logger("app.workers").info("arq_worker_startup", env=settings.app_env)


async def on_shutdown(_ctx: dict[str, object]) -> None:
    """Log clean shutdown of the ARQ worker."""
    get_logger("app.workers").info("arq_worker_shutdown")


class WorkerSettings:
    """ARQ entrypoint (`arq app.workers.settings.WorkerSettings`)."""

    functions: ClassVar[list[WorkerTask]] = [worker_ping]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
