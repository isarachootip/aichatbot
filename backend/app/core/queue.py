"""Async background job enqueuer protocol backed by ARQ Redis pool."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol, runtime_checkable

from arq.connections import ArqRedis, RedisSettings, create_pool


@runtime_checkable
class JobEnqueuer(Protocol):
    """Queue interface allowing FastAPI handlers to enqueue deferred ARQ jobs."""

    async def enqueue(
        self,
        function_name: str,
        *args: object,
        defer_by: timedelta | None = None,
    ) -> str | None:
        """Enqueue a background task and return its job ID if assigned."""
        ...

    async def close(self) -> None:
        """Release underlying Redis connection pool resources."""
        ...


class ArqJobEnqueuer:
    """Production ARQ job enqueuer using a lazy Redis connection pool."""

    def __init__(self, redis_url: str) -> None:
        self._redis_settings = RedisSettings.from_dsn(redis_url)
        self._pool: ArqRedis | None = None

    async def _get_pool(self) -> ArqRedis:
        if self._pool is None:
            self._pool = await create_pool(self._redis_settings)
        return self._pool

    async def enqueue(
        self,
        function_name: str,
        *args: object,
        defer_by: timedelta | None = None,
    ) -> str | None:
        pool = await self._get_pool()
        job = await pool.enqueue_job(function_name, *args, _defer_by=defer_by)
        return str(job.job_id) if job is not None else None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


@dataclass(frozen=True)
class EnqueuedJob:
    """Recorded job entry captured by InMemoryJobEnqueuer in tests."""

    function_name: str
    args: tuple[object, ...]
    defer_by: timedelta | None


class InMemoryJobEnqueuer:
    """Deterministic in-memory job collector for FastAPI webhook tests."""

    def __init__(self) -> None:
        self.jobs: list[EnqueuedJob] = []

    async def enqueue(
        self,
        function_name: str,
        *args: object,
        defer_by: timedelta | None = None,
    ) -> str | None:
        self.jobs.append(EnqueuedJob(function_name=function_name, args=args, defer_by=defer_by))
        return f"mem-job-{len(self.jobs)}"

    async def close(self) -> None:
        """No-op for in-memory enqueuer."""
